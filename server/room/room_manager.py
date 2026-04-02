# room/room_manager.py — 房间主管理器
# 这是房间模块的总协调入口，组合所有子服务，对外暴露 connect / disconnect / handle_action。
# app.py 的 WebSocket 路由只与此类交互。

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import WebSocket

from game import ChinitsuGame
from redis_client import get_redis
from room.models import (
    Room, PlayerSession, RoomStatus, RoomEvent,
    ROOM_MAX_LIFETIME_SEC, DEFAULT_ROUND_LIMIT,
)
from room import state_machine
from room import protocol
from room.errors import (
    WS_CLOSE_ROOM_FULL, WS_CLOSE_DUPLICATE_ID, WS_CLOSE_INVALID_ROOM,
    WS_CLOSE_ROOM_EXPIRED, WS_CLOSE_ROOM_CLOSED,
    ERR_GAME_NOT_STARTED, ERR_GAME_PAUSED, ERR_GAME_ENDED,
    ERR_NOT_ENOUGH_PLAYERS, ERR_UNKNOWN_ACTION, ERR_ROUND_NOT_ENDED,
    InvalidTransitionError,
)
from room.push_service import PushService
from room.snapshot_manager import SnapshotManager
from room.timeout_scheduler import TimeoutScheduler
from room.ready_service import ReadyService
from room.end_decision_service import EndDecisionService
from room.reconnect_manager import ReconnectManager
from room import match_end_evaluator

logger = logging.getLogger("uvicorn")

# 房间层处理的 action（不转发给游戏层）
_ROOM_ACTIONS = {"start", "start_new", "cancel_start", "continue_game", "end_game", "leave_room"}

# 游戏层处理的 action
_GAME_ACTIONS = {"draw", "discard", "riichi", "kan", "tsumo", "ron", "skip_ron"}


class RoomManager:
    """
    房间主管理器 — 所有房间操作的唯一入口。
    持有：
    - rooms: 内存中所有活跃 Room 对象
    - sessions: 内存中所有 PlayerSession（room_name → {user_id → session}）
    - games: 内存中所有 ChinitsuGame 实例
    - 以及所有子服务的引用
    """

    def __init__(self):
        # ── 内存数据存储 ────────────────────────────────
        self.rooms: dict[str, Room] = {}
        self.sessions: dict[str, dict[str, PlayerSession]] = {}
        self.games: dict[str, ChinitsuGame] = {}

        # ── 子服务 ─────────────────────────────────────
        self.push = PushService(self.sessions)
        self.snapshot_mgr = SnapshotManager()
        self.timers = TimeoutScheduler()
        self.ready_svc = ReadyService()
        self.end_svc = EndDecisionService()
        self.reconnect_mgr = ReconnectManager(self)

    # ================================================================
    # 公开接口：connect / disconnect / handle_action
    # ================================================================

    async def connect(
        self, ws: WebSocket, room_name: str, user_id: str, display_name: str
    ) -> bool:
        """
        玩家建立 WebSocket 连接时调用。
        处理：创建房间 / 加入房间 / 断线重连。
        返回 True 表示连接成功（ws 已 accept），False 表示拒绝。
        """
        # 用于防止重复 accept：RECONNECT 分支可能已提前 accept
        ws_accepted = False

        # 校验房间名
        if not self._validate_room_name(room_name):
            await ws.accept()
            code, reason = WS_CLOSE_INVALID_ROOM
            await ws.close(code=code, reason=reason)
            return False

        room = self.rooms.get(room_name)

        # ── 场景 1：房间处于 RECONNECT，尝试重连 ──────
        if room is not None and room.status == RoomStatus.RECONNECT:
            session = self.get_session(room_name, user_id)
            if session is not None and not session.online and user_id in room.player_ids:
                await ws.accept()
                ws_accepted = True
                success = await self.reconnect_mgr.on_reconnect(
                    ws, room_name, user_id, display_name
                )
                if success:
                    return True
                # 重连失败，继续走常规加入流程（ws 已 accept，后续跳过重复 accept）

        # ── 场景 2：房间已存在，检查能否加入 ──────────
        if room is not None:
            # 满员检查
            if room.is_full:
                if not ws_accepted:
                    await ws.accept()
                code, reason = WS_CLOSE_ROOM_FULL
                await ws.close(code=code, reason=reason)
                return False
            # 重复 ID 检查（仅在线玩家才拒绝，已离线的允许重新加入）
            if user_id in room.player_ids:
                session = self.get_session(room_name, user_id)
                if session and session.online:
                    if not ws_accepted:
                        await ws.accept()
                    code, reason = WS_CLOSE_DUPLICATE_ID
                    await ws.close(code=code, reason=reason)
                    return False

        # ── 接受连接 ─────────────────────────────────
        if not ws_accepted:
            await ws.accept()

        if room is None:
            # 场景 3：房间不存在 → 创建房间
            await self._create_room(ws, room_name, user_id, display_name)
        else:
            # 场景 4：房间存在且有空位 → 加入
            await self._join_room(ws, room, user_id, display_name)

        return True

    async def disconnect(
        self, ws: WebSocket, room_name: str, user_id: str
    ) -> None:
        """
        玩家 WebSocket 断开时调用。
        根据当前房间状态执行不同的清理逻辑。
        """
        session = self.get_session(room_name, user_id)
        if session is None:
            return

        # 获取 connection_id 用于旧连接保护
        connection_id = session.connection_id

        # 委托给 ReconnectManager 统一处理
        await self.reconnect_mgr.on_disconnect(room_name, user_id, connection_id)

    async def handle_action(
        self, data: dict, room_name: str, user_id: str
    ) -> None:
        """
        处理客户端发送的 action。
        根据房间状态分发到房间层或游戏层。
        """
        room = self.rooms.get(room_name)
        if room is None:
            return

        action = data.get("action", "")
        card_idx_raw = data.get("card_idx", "")
        card_idx = int(card_idx_raw) if isinstance(card_idx_raw, str) and card_idx_raw.isdigit() else None

        # ── 状态级拦截 ─────────────────────────────
        if room.status == RoomStatus.RECONNECT:
            await self.push.unicast(room_name, user_id, protocol.make_error(ERR_GAME_PAUSED))
            return

        if room.status == RoomStatus.WAITING:
            if action in ("start", "start_new"):
                await self._handle_start(room, user_id, card_idx)
            elif action == "cancel_start":
                await self._handle_cancel_start(room, user_id)
            elif action == "leave_room":
                await self._handle_leave_room(room, user_id)
            else:
                await self.push.unicast(room_name, user_id,
                                        protocol.make_error(ERR_GAME_NOT_STARTED))
            return

        if room.status == RoomStatus.ENDED:
            if action == "continue_game":
                await self._handle_continue_game(room, user_id)
            elif action == "end_game":
                await self._handle_end_game(room, user_id)
            elif action == "leave_room":
                await self._handle_leave_room(room, user_id)
            elif action in ("start", "start_new"):
                # 兼容：在 ENDED 中把 start_new 映射为 continue_game
                await self._handle_continue_game(room, user_id)
            else:
                await self.push.unicast(room_name, user_id,
                                        protocol.make_error(ERR_GAME_ENDED))
            return

        if room.status == RoomStatus.RUNNING:
            if action in ("start", "start_new"):
                # RUNNING 中的 start/start_new → 轮次间重启
                await self._handle_round_restart(room, user_id, card_idx)
            elif action in _GAME_ACTIONS:
                await self._handle_game_action(room, action, card_idx, user_id)
            else:
                await self.push.unicast(room_name, user_id,
                                        protocol.make_error(ERR_UNKNOWN_ACTION))
            return

    # ================================================================
    # 内部方法：房间创建 / 加入
    # ================================================================

    async def _create_room(
        self, ws: WebSocket, room_name: str, user_id: str, display_name: str
    ) -> None:
        """创建新房间（[空] → WAITING）"""
        now = time.time()
        room_id = str(uuid.uuid4())

        room = Room(
            room_id=room_id,
            room_name=room_name,
            status=RoomStatus.WAITING,
            owner_id=user_id,
            player_ids=[user_id],
            created_at=now,
            updated_at=now,
            expires_at=now + ROOM_MAX_LIFETIME_SEC,
            round_limit=DEFAULT_ROUND_LIMIT,
        )
        self.rooms[room_name] = room

        # 创建玩家会话
        session = PlayerSession(
            user_id=user_id,
            display_name=display_name,
            room_name=room_name,
            seat=0,
            is_owner=True,
            ws=ws,
        )
        self.sessions[room_name] = {user_id: session}

        # 同步到 Redis
        await self._sync_room_to_redis(room)
        await self._sync_session_to_redis(session)

        # 启动 40 分钟房间寿命计时器
        timer_key = f"room_expire:{room_name}"
        await self.timers.schedule(
            timer_key,
            ROOM_MAX_LIFETIME_SEC,
            self._on_room_expired,
            room_name, room_id,
        )

        # 通知房主
        await self.push.unicast(room_name, user_id, {
            "broadcast": False,
            "event": "room_created",
            "room_name": room_name,
            "user_id": user_id,
            "display_name": display_name,
            "is_owner": True,
        })

        logger.info("房间创建 [%s] 房主=%s(%s)", room_name, display_name, user_id[:8])

    async def _join_room(
        self, ws: WebSocket, room: Room, user_id: str, display_name: str
    ) -> None:
        """加入已存在的房间"""
        room_name = room.room_name

        # 如果该玩家之前在房间中（例如 WAITING 断线后重连），更新会话
        existing = self.get_session(room_name, user_id)
        if existing is not None:
            existing.mark_online(ws)
            await self._sync_session_to_redis(existing)
        else:
            # 新玩家加入
            seat = len(room.player_ids)
            session = PlayerSession(
                user_id=user_id,
                display_name=display_name,
                room_name=room_name,
                seat=seat,
                is_owner=False,
                ws=ws,
            )
            room.player_ids.append(user_id)
            if room_name not in self.sessions:
                self.sessions[room_name] = {}
            self.sessions[room_name][user_id] = session
            room.touch()

            await self._sync_room_to_redis(room)
            await self._sync_session_to_redis(session)

        # 广播通知
        await self.push.broadcast(
            room_name,
            protocol.make_player_joined(display_name, room_name, len(room.player_ids)),
        )

        logger.info("玩家加入 [%s] %s(%s) 当前%d人",
                     room_name, display_name, user_id[:8], len(room.player_ids))

    # ================================================================
    # 内部方法：房间层 action 处理
    # ================================================================

    async def _handle_start(self, room: Room, user_id: str, card_idx: int | None) -> None:
        """
        WAITING 中处理 start 请求。
        使用 ReadyService 管理双确认。
        """
        room_name = room.room_name
        online_ids = self.push.get_online_user_ids(room_name)

        if len(online_ids) < 2:
            await self.push.unicast(room_name, user_id,
                                    protocol.make_error(ERR_NOT_ENOUGH_PLAYERS))
            return

        result = self.ready_svc.mark_ready(room_name, user_id, online_ids, card_idx)

        if not result.all_ready:
            # 广播准备状态变更
            await self.push.broadcast(room_name, protocol.make_start_ready_changed(
                ready_user_ids=result.ready_ids,
                all_ready=False,
            ))
            return

        # ── 双方都 ready → 启动游戏 ────────────────
        debug_code = result.debug_code
        self.ready_svc.clear(room_name)

        await self._start_game(room, debug_code)

    async def _handle_cancel_start(self, room: Room, user_id: str) -> None:
        """取消准备状态"""
        room_name = room.room_name
        remaining = self.ready_svc.cancel_ready(room_name, user_id)
        await self.push.broadcast(room_name, protocol.make_start_ready_changed(
            ready_user_ids=remaining,
            all_ready=False,
        ))

    async def _handle_round_restart(self, room: Room, user_id: str, card_idx: int | None) -> None:
        """
        RUNNING 中处理 start / start_new（轮次间重启）。
        当前轮结束后（game.status==ENDED），双方通过 start_new 开始下一轮。
        """
        room_name = room.room_name
        game = self.games.get(room_name)

        if game is None:
            return

        # 只有当游戏层状态为 ENDED（一轮结束）时才允许 start_new
        if not game.is_ended:
            await self.push.unicast(room_name, user_id,
                                    protocol.make_error(ERR_ROUND_NOT_ENDED))
            return

        online_ids = self.push.get_online_user_ids(room_name)
        if len(online_ids) < 2:
            await self.push.unicast(room_name, user_id,
                                    protocol.make_error(ERR_NOT_ENOUGH_PLAYERS))
            return

        result = self.ready_svc.mark_ready(room_name, user_id, online_ids, card_idx)

        if not result.all_ready:
            # 通知双方准备状态
            await self.push.broadcast(room_name, protocol.make_start_ready_changed(
                ready_user_ids=result.ready_ids,
                all_ready=False,
            ))
            # 同时给请求方一个确认
            await self.push.unicast(room_name, user_id, {
                "broadcast": False,
                "action": "start_new",
                "message": "waiting_for_opponent",
            })
            return

        # ── 双方 ready → 开始下一轮 ────────────────
        debug_code = result.debug_code
        self.ready_svc.clear(room_name)

        await self._start_next_round(room, game, debug_code)

    async def _handle_continue_game(self, room: Room, user_id: str) -> None:
        """ENDED 中处理 continue_game"""
        room_name = room.room_name
        online_ids = self.push.get_online_user_ids(room_name)

        result = self.end_svc.choose_continue(room_name, user_id, online_ids)

        if not result.all_continue:
            await self.push.broadcast(room_name, protocol.make_continue_vote_changed(
                continue_user_ids=result.continue_ids,
                all_continue=False,
            ))
            return

        # 双方都选择继续 → 回到 WAITING
        self.end_svc.clear(room_name)
        self.ready_svc.clear(room_name)

        try:
            await self._do_transition(room, RoomEvent.BOTH_CONTINUE)
        except InvalidTransitionError:
            return

        # 重置比赛状态
        room.round_no = 0

        # 清理旧游戏实例
        if room_name in self.games:
            del self.games[room_name]

        await self.push.broadcast(room_name, {
            "broadcast": True,
            "event": "match_restarted",
            "room_status": room.status.value,
        })

        logger.info("双方选择继续，房间回到 WAITING [%s]", room_name)

    async def _handle_end_game(self, room: Room, user_id: str) -> None:
        """ENDED 中处理 end_game → 直接销毁房间"""
        room_name = room.room_name
        session = self.get_session(room_name, user_id)
        display_name = session.display_name if session else user_id

        logger.info("玩家 %s 选择结束游戏 [%s]", display_name, room_name)

        await self.push.broadcast(room_name, protocol.make_room_closed("player_end_game"))

        try:
            await self._do_transition(room, RoomEvent.ANY_END_GAME)
        except InvalidTransitionError:
            pass

        await self.cleanup_room(room_name, room.room_id, "end_game")

    async def _handle_leave_room(self, room: Room, user_id: str) -> None:
        """处理 leave_room：断开该玩家的连接"""
        room_name = room.room_name
        session = self.get_session(room_name, user_id)
        if session and session.ws:
            try:
                await session.ws.close(code=1000, reason="leave_room")
            except Exception:
                pass
        # disconnect 会由 WebSocketDisconnect 异常触发

    # ================================================================
    # 内部方法：游戏层 action 处理
    # ================================================================

    async def _handle_game_action(
        self, room: Room, action: str, card_idx: int | None, user_id: str
    ) -> None:
        """
        转发游戏操作到 ChinitsuGame.input()，并处理后续逻辑：
        - 发送结果给双方
        - 保存快照
        - 评估比赛是否结束
        """
        room_name = room.room_name
        game = self.games.get(room_name)

        if game is None:
            await self.push.unicast(room_name, user_id,
                                    protocol.make_error(ERR_GAME_NOT_STARTED))
            return

        # 确保有 2 名在线玩家（防止 RUNNING 但对手刚断线瞬间的操作）
        online_ids = self.push.get_online_user_ids(room_name)
        if len(online_ids) < 2:
            await self.push.unicast(room_name, user_id,
                                    protocol.make_error(ERR_GAME_PAUSED))
            return

        # 调用游戏层处理
        try:
            result = game.input(action, card_idx, user_id)
        except Exception as e:
            logger.exception("游戏层异常 [%s] action=%s: %s", room_name, action, e)
            await self.push.unicast(room_name, user_id,
                                    protocol.make_error("game_error", str(e)))
            return

        if not result:
            return

        # 将 wall_count 注入到结果中（前端需要）
        wall_count = len(game.yama) if hasattr(game, 'yama') else 0

        # 发送结果给各玩家
        for target_id, info in result.items():
            info["broadcast"] = False
            info["wall_count"] = wall_count
            await self.push.unicast(room_name, target_id, info)

        # ── 游戏后续处理 ──────────────────────────
        # 检查该轮是否结束
        round_just_ended = game.is_ended

        if round_just_ended:
            # 本轮结束，增加轮次计数
            room.round_no += 1
            logger.info("第 %d 轮结束 [%s]", room.round_no, room_name)

        # 保存快照
        snapshot = self.snapshot_mgr.serialize_game(
            game, room_name, room.round_no, room.round_limit,
            display_names=self.get_display_names(room_name),
        )
        await self.snapshot_mgr.save_snapshot(room_name, snapshot)

        # 评估比赛是否应该结束
        if round_just_ended:
            decision = match_end_evaluator.evaluate(snapshot)
            if decision.should_end:
                await self._handle_match_end(room, snapshot, decision.reason)

    async def _handle_match_end(self, room: Room, snapshot: dict, reason: str) -> None:
        """比赛结束：RUNNING → ENDED"""
        room_name = room.room_name

        try:
            await self._do_transition(room, RoomEvent.MATCH_END)
        except InvalidTransitionError:
            return

        # 清空投票状态
        self.ready_svc.clear(room_name)
        self.end_svc.clear(room_name)

        # 构造最终分数
        players = snapshot.get("players", {})
        final_scores = {pid: pdata.get("point", 0) for pid, pdata in players.items()}

        # 广播比赛结束
        await self.push.broadcast(room_name, protocol.make_match_ended(reason, final_scores))

        logger.info("比赛结束 [%s] 原因=%s 分数=%s", room_name, reason, final_scores)

    # ================================================================
    # 内部方法：游戏启动
    # ================================================================

    async def _start_game(self, room: Room, debug_code: int | None = None) -> None:
        """
        WAITING → RUNNING：创建游戏实例并启动第一轮。
        """
        room_name = room.room_name

        # 创建游戏实例
        game = ChinitsuGame()
        for uid in room.player_ids:
            game.add_player(uid)

        self.games[room_name] = game

        # 启动第一轮
        game.start_new_game(debug_code=debug_code)
        game.state.next()  # 庄家第一巡不需要摸牌，直接进入 AFTER_DRAW
        game.set_running()

        # 状态转移：WAITING → RUNNING
        try:
            await self._do_transition(room, RoomEvent.BOTH_READY)
        except InvalidTransitionError:
            logger.error("状态转移失败: WAITING → RUNNING [%s]", room_name)
            return

        room.game_id = room_name
        room.round_no = 0

        # 构建初始游戏状态并发送给双方
        await self._send_game_start_state(room, game)

        # 保存初始快照
        snapshot = self.snapshot_mgr.serialize_game(
            game, room_name, room.round_no, room.round_limit,
            display_names=self.get_display_names(room_name),
        )
        await self.snapshot_mgr.save_snapshot(room_name, snapshot)

        logger.info("游戏开始 [%s] 玩家=%s", room_name, room.player_ids)

    async def _start_next_round(
        self, room: Room, game: ChinitsuGame, debug_code: int | None = None
    ) -> None:
        """
        RUNNING 中启动下一轮（轮次间重启）。
        """
        room_name = room.room_name

        game.start_new_game(debug_code=debug_code)
        game.state.next()
        game.set_running()

        # 构建并发送游戏状态
        await self._send_game_start_state(room, game)

        # 保存快照
        snapshot = self.snapshot_mgr.serialize_game(
            game, room_name, room.round_no, room.round_limit,
            display_names=self.get_display_names(room_name),
        )
        await self.snapshot_mgr.save_snapshot(room_name, snapshot)

        logger.info("第 %d 轮开始 [%s]", room.round_no + 1, room_name)

    async def _send_game_start_state(self, room: Room, game: ChinitsuGame) -> None:
        """发送游戏初始状态给双方（手牌、庄家信息等）"""
        room_name = room.room_name
        wall_count = len(game.yama)

        for uid in room.player_ids:
            player = game.player(uid)
            opp = game.other_player(uid)
            info = {
                "broadcast": False,
                "event": "game_started",
                "action": "start",
                "message": "ok",
                "hand": player.hand,
                "is_oya": player.is_oya,
                "wall_count": wall_count,
                "round_no": room.round_no,
                "round_limit": room.round_limit,
                # 公共信息
                "balances": {pid: game.player(pid).point for pid in game.player_ids},
                "fuuro": {pid: game.player(pid).fuuro for pid in game.player_ids},
                "kawa": {pid: game.player(pid).kawa for pid in game.player_ids},
                "player_id": uid,
            }
            await self.push.unicast(room_name, uid, info)

    # ================================================================
    # 内部方法：状态转移与房间清理
    # ================================================================

    async def _do_transition(self, room: Room, event: RoomEvent) -> None:
        """
        执行房间状态转移。
        由各处理方法调用，统一记录日志和同步 Redis。
        """
        old_status = room.status
        new_status = state_machine.transition(room.status, event)
        room.status = new_status
        room.touch()

        logger.info("状态转移 [%s]: %s --%s--> %s",
                     room.room_name, old_status.value, event.value, new_status.value)

        await self._sync_room_to_redis(room)

    async def cleanup_room(self, room_name: str, room_id: str, reason: str) -> None:
        """
        销毁房间：清理所有内存数据、Redis 数据、定时器。
        room_id 参数用于幂等保护（防止误删新建的同名房间）。
        """
        room = self.rooms.get(room_name)
        if room is not None and room.room_id != room_id:
            logger.debug("cleanup_room 跳过：room_id 不匹配 [%s]", room_name)
            return

        logger.info("销毁房间 [%s] 原因=%s", room_name, reason)

        # 关闭所有连接
        await self.push.close_all_connections(
            room_name,
            code=WS_CLOSE_ROOM_CLOSED[0],
            reason=reason,
        )

        # 取消所有定时器
        await self.timers.cancel_prefix(f"room_expire:{room_name}")
        await self.timers.cancel_prefix(f"reconnect:{room_name}")
        await self.timers.cancel_prefix(f"skip_ron:{room_name}")
        await self.timers.cancel_prefix(f"action:{room_name}")

        # 清理子服务数据
        self.ready_svc.cleanup_room(room_name)
        self.end_svc.cleanup_room(room_name)
        await self.snapshot_mgr.delete_snapshot(room_name)

        # 清理 Redis
        await self._cleanup_redis(room_name)

        # 清理内存
        self.rooms.pop(room_name, None)
        self.sessions.pop(room_name, None)
        self.games.pop(room_name, None)

    # ================================================================
    # 辅助方法
    # ================================================================

    def get_session(self, room_name: str, user_id: str) -> PlayerSession | None:
        """获取指定玩家的会话"""
        return self.sessions.get(room_name, {}).get(user_id)

    def get_display_names(self, room_name: str) -> dict[str, str]:
        """从 session 中获取房间内所有玩家的昵称映射 {user_id: display_name}"""
        return {
            uid: s.display_name
            for uid, s in self.sessions.get(room_name, {}).items()
        }

    def _remove_player_from_room(self, room_name: str, user_id: str) -> None:
        """从房间中移除玩家（仅用于 WAITING/ENDED 断线）"""
        room = self.rooms.get(room_name)
        if room and user_id in room.player_ids:
            room.player_ids.remove(user_id)
            room.touch()

        # 同时从游戏中移除（如果游戏存在）
        game = self.games.get(room_name)
        if game and user_id in game.player_ids:
            try:
                game.remove_player(user_id)
            except Exception:
                pass  # 游戏可能不允许移除（RUNNING 中），忽略

        # 清理会话
        room_sessions = self.sessions.get(room_name, {})
        room_sessions.pop(user_id, None)

    @staticmethod
    def _validate_room_name(room_name: str) -> bool:
        """校验房间名：1~20 字符"""
        return 1 <= len(room_name) <= 20

    # ================================================================
    # Redis 同步
    # ================================================================

    async def _sync_room_to_redis(self, room: Room) -> None:
        """将 Room 状态同步到 Redis"""
        redis = get_redis()
        if redis is None:
            return
        try:
            key = f"room:{room.room_name}"
            await redis.hset(key, mapping=room.to_redis_dict())
            await redis.sadd("room_index", room.room_name)
        except Exception as e:
            logger.warning("同步 Room 到 Redis 失败 [%s]: %s", room.room_name, e)

    async def _sync_session_to_redis(self, session: PlayerSession) -> None:
        """将 PlayerSession 同步到 Redis"""
        redis = get_redis()
        if redis is None:
            return
        try:
            key = f"player_session:{session.room_name}:{session.user_id}"
            await redis.hset(key, mapping=session.to_redis_dict())
        except Exception as e:
            logger.warning("同步 Session 到 Redis 失败 [%s/%s]: %s",
                           session.room_name, session.user_id, e)

    async def _cleanup_redis(self, room_name: str) -> None:
        """清理 Redis 中该房间的所有数据"""
        redis = get_redis()
        if redis is None:
            return
        try:
            # 合并 room.player_ids 与 sessions.keys()：
            # 两者取并集确保在大厅断线（已从 player_ids 移除但 session key 还留在 Redis）
            # 的玩家记录也能被正确清除。
            room = self.rooms.get(room_name)
            from_room = set(room.player_ids if room else [])
            from_sessions = set(self.sessions.get(room_name, {}).keys())
            player_ids = from_room | from_sessions

            keys_to_delete = [f"room:{room_name}", f"snapshot:{room_name}"]
            for pid in player_ids:
                keys_to_delete.append(f"player_session:{room_name}:{pid}")

            if keys_to_delete:
                await redis.delete(*keys_to_delete)
            await redis.srem("room_index", room_name)
        except Exception as e:
            logger.warning("清理 Redis 失败 [%s]: %s", room_name, e)

    async def _on_room_expired(self, room_name: str, room_id: str) -> None:
        """
        房间 40 分钟寿命到期回调。
        无论当前状态如何，都销毁房间。
        """
        room = self.rooms.get(room_name)
        if room is None:
            return
        if room.room_id != room_id:
            return  # 同名新房间，旧 timer 不应生效

        logger.info("房间寿命到期 [%s]", room_name)

        # 通知在线玩家
        await self.push.broadcast(room_name, protocol.make_room_expired(room_name))

        # 执行销毁
        try:
            await self._do_transition(room, RoomEvent.ROOM_EXPIRED)
        except InvalidTransitionError:
            pass

        await self.cleanup_room(room_name, room_id, "room_expired")
