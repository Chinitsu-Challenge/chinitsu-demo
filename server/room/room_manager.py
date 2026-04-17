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
    Room, PlayerSession, SpectatorSession, RoomStatus, RoomEvent,
    ROOM_MAX_LIFETIME_SEC, RECONNECT_TIMEOUT_SEC, DEFAULT_ROUND_LIMIT, MAX_SPECTATORS_PER_ROOM,
)
from room import state_machine
from room import protocol
from room.errors import (
    WS_CLOSE_ROOM_FULL, WS_CLOSE_DUPLICATE_ID, WS_CLOSE_INVALID_ROOM,
    WS_CLOSE_ROOM_EXPIRED, WS_CLOSE_ROOM_CLOSED, WS_CLOSE_ALREADY_IN_ROOM,
    WS_CLOSE_SPECTATOR_ROOM_FULL,
    ERR_GAME_NOT_STARTED, ERR_GAME_PAUSED, ERR_GAME_ENDED,
    ERR_NOT_ENOUGH_PLAYERS, ERR_UNKNOWN_ACTION, ERR_ROUND_NOT_ENDED,
    ERR_SPECTATOR_ACTION_FORBIDDEN,
    InvalidTransitionError,
)
from room.push_service import PushService
from room.snapshot_manager import SnapshotManager
from room.timeout_scheduler import TimeoutScheduler
from room.ready_service import ReadyService
from room.end_decision_service import EndDecisionService
from room.reconnect_manager import ReconnectManager
from room.bot_service import BotService
from room import match_end_evaluator
from bot_player import BOT_ID

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
        self.spectators: dict[str, dict[str, SpectatorSession]] = {}
        self.games: dict[str, ChinitsuGame] = {}

        # ── 子服务 ─────────────────────────────────────
        self.push = PushService(self.sessions, self.spectators)
        self.snapshot_mgr = SnapshotManager()
        self.timers = TimeoutScheduler()
        self.ready_svc = ReadyService()
        self.end_svc = EndDecisionService()
        self.reconnect_mgr = ReconnectManager(self)
        self.bot_svc = BotService(self)

    # ================================================================
    # 启动恢复：从 Redis 重建内存状态
    # ================================================================

    async def startup_restore(self) -> None:
        """
        服务重启后从 Redis 恢复房间状态。
        在 lifespan 中 Redis 初始化完成后调用，先于任何 WebSocket 连接建立。
        """
        redis = get_redis()
        if redis is None:
            logger.info("[startup] Redis 不可用，跳过房间恢复")
            return

        try:
            room_names = await redis.smembers("room_index")
        except Exception as e:
            logger.error("[startup] 读取 room_index 失败: %s", e)
            return

        if not room_names:
            logger.info("[startup] Redis 中无活跃房间，无需恢复")
            return

        logger.info("[startup] 发现 %d 个待恢复房间", len(room_names))
        restored = skipped = 0
        for raw_name in room_names:
            room_name = raw_name if isinstance(raw_name, str) else raw_name.decode()
            try:
                ok = await self._restore_one_room(room_name)
                if ok:
                    restored += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error("[startup] 恢复房间异常 [%s]: %s", room_name, e)
                skipped += 1

        logger.info("[startup] 房间恢复完成：成功 %d，跳过/清理 %d", restored, skipped)

    async def _restore_one_room(self, room_name: str) -> bool:
        """
        从 Redis 恢复单个房间到内存。
        返回 True = 已写入内存；False = 跳过（过期/已销毁/数据损坏）。
        """
        redis = get_redis()

        # ── 1. 加载并解析 Room ─────────────────────────────────────
        try:
            room_data = await redis.hgetall(f"room:{room_name}")
        except Exception as e:
            logger.warning("[startup] 读取 Room 数据失败 [%s]: %s", room_name, e)
            return False

        if not room_data:
            # room_index 中有条目但 Hash 不存在，清理脏索引
            try:
                await redis.srem("room_index", room_name)
            except Exception:
                pass
            return False

        try:
            room = Room.from_redis_dict(room_data)
        except Exception as e:
            logger.warning("[startup] 解析 Room 数据失败 [%s]: %s", room_name, e)
            return False

        # ── 2. 跳过终态 / 过期房间 ─────────────────────────────────
        if room.status == RoomStatus.DESTROYED:
            logger.info("[startup] 跳过 DESTROYED 房间 [%s]，清理 Redis", room_name)
            await self._cleanup_redis(room_name)
            return False

        now = time.time()
        if room.expires_at <= now:
            logger.info("[startup] 房间已过期 [%s]（expires_at=%.0f），清理 Redis", room_name, room.expires_at)
            await self._cleanup_redis(room_name)
            return False

        # ── 3. 加载 PlayerSession（所有玩家标记为离线）──────────────
        sessions: dict[str, PlayerSession] = {}
        for pid in room.player_ids:
            if pid == BOT_ID:
                continue  # bot 无实体会话
            try:
                sd = await redis.hgetall(f"player_session:{room_name}:{pid}")
                if sd:
                    session = PlayerSession.from_redis_dict(sd)
                    session.mark_offline()  # 重启后所有玩家均处于离线状态
                    sessions[pid] = session
            except Exception as e:
                logger.warning("[startup] 读取 Session 失败 [%s/%s]: %s", room_name, pid, e)

        # ── 4. 写入内存 ────────────────────────────────────────────
        self.rooms[room_name] = room
        self.sessions[room_name] = sessions
        original_status = room.status

        # ── 5. 按状态分类处理 ─────────────────────────────────────
        if room.status in (RoomStatus.RUNNING, RoomStatus.RECONNECT):
            # 服务重启等价于全员断线，尝试从快照完整恢复
            snapshot = await self.snapshot_mgr.load_snapshot(room_name)

            if snapshot and "yama" in snapshot:
                # 新格式快照：包含 yama，可完整重建游戏对象，进入 RECONNECT 等待玩家回来
                room.status = RoomStatus.RECONNECT
                await self._sync_room_to_redis(room)

                try:
                    game = ChinitsuGame.from_snapshot(snapshot)
                    self.games[room_name] = game
                    logger.info("[startup] 游戏对象已从快照重建 [%s]", room_name)
                except Exception as e:
                    logger.warning("[startup] 游戏对象重建失败 [%s]: %s", room_name, e)

                # 为每名人类玩家启动重连超时计时器（给满额的 RECONNECT_TIMEOUT_SEC）
                for pid in sessions:
                    await self.timers.schedule(
                        f"reconnect:{room_name}:{pid}",
                        RECONNECT_TIMEOUT_SEC,
                        self.reconnect_mgr._on_reconnect_timeout,
                        room_name, room.room_id, pid,
                    )

                logger.info("[startup] 已恢复为 RECONNECT [%s]（原=%s），%d 名玩家等待重连",
                            room_name, original_status.value, len(sessions))
            else:
                # 旧格式快照（无 yama）或无快照：无法继续游戏，重置为 WAITING 让玩家重新开始
                room.status = RoomStatus.WAITING
                room.ready_user_ids = set()
                room.continue_user_ids = set()
                await self._sync_room_to_redis(room)
                await self.snapshot_mgr.delete_snapshot(room_name)
                reason = "快照缺少 yama 字段（旧格式）" if snapshot else "无快照"
                logger.info("[startup] 无法恢复游戏 [%s]（%s），重置为 WAITING", room_name, reason)

        elif room.status == RoomStatus.WAITING:
            logger.info("[startup] 恢复 WAITING 房间 [%s]，%d 名玩家", room_name, len(sessions))

        elif room.status == RoomStatus.ENDED:
            # 预加载快照到内存，方便玩家重连时推送 game_snapshot
            await self.snapshot_mgr.load_snapshot(room_name)
            logger.info("[startup] 恢复 ENDED 房间 [%s]", room_name)

        # ── 6. 重新调度房间寿命计时器（剩余时间）────────────────────
        remaining_lifetime = max(30.0, room.expires_at - now)
        await self.timers.schedule(
            f"room_expire:{room_name}",
            remaining_lifetime,
            self._on_room_expired,
            room_name, room.room_id,
        )

        return True

    # ================================================================
    # 公开接口：connect / disconnect / handle_action
    # ================================================================

    async def connect(
        self,
        ws: WebSocket,
        room_name: str,
        user_id: str,
        display_name: str,
        vs_bot: bool = False,
        bot_level: str = "normal",
        rules: dict = None,
        debug_code: int = None,
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

        # ── 防御性检查：DESTROYED 僵尸房间 ────────────
        # cleanup_room 的中间步骤若抛出异常，rooms.pop 可能未执行，
        # 导致状态为 DESTROYED 的房间残留在内存中。
        # 将其视为不存在，清理内存残留，走创建新房间流程。
        if room is not None and room.status == RoomStatus.DESTROYED:
            logger.warning("发现内存中的僵尸房间 [%s]，清理并重建", room_name)
            self.rooms.pop(room_name, None)
            self.sessions.pop(room_name, None)
            self.spectators.pop(room_name, None)
            self.games.pop(room_name, None)
            room = None

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

        # ── 场景 1b：ENDED 中离线玩家重连 ─────────────
        # 必须在满员检查之前：房间满员但该玩家是其中一个离线成员
        if room is not None and room.status == RoomStatus.ENDED:
            session = self.get_session(room_name, user_id)
            if session is not None and not session.online and user_id in room.player_ids:
                if not ws_accepted:
                    await ws.accept()
                    ws_accepted = True
                session.mark_online(ws)
                await self._sync_session_to_redis(session)
                # 发送末局快照，让前端恢复到正确的 ended 状态
                snapshot = await self.snapshot_mgr.load_snapshot(room_name)
                if snapshot:
                    player_view = self.snapshot_mgr.build_player_view(snapshot, user_id)
                    await self.push.unicast(room_name, user_id, player_view)
                    # 恢复结算界面：补发 match_ended 事件（内含 matchResult）。
                    # 仅靠 game_snapshot 前端只会还原 phase='ended'，
                    # 但 matchResult 为 null → MatchEndOverlay 不显示。
                    match_result = snapshot.get("match_result")
                    if match_result:
                        await self.push.unicast(room_name, user_id, {
                            "broadcast": True,
                            "event": "match_ended",
                            "reason": match_result.get("reason", ""),
                            "final_scores": match_result.get("final_scores", {}),
                            "winner_id": match_result.get("winner_id"),
                        })
                logger.info("ENDED 中玩家重连 [%s] %s(%s)", room_name, display_name, user_id[:8])
                return True

        # ── 场景 1c：WAITING 中离线玩家重连 ──────────────
        # 必须在满员检查之前：双人 WAITING 满员但该玩家是其中一个离线成员
        if room is not None and room.status == RoomStatus.WAITING:
            session = self.get_session(room_name, user_id)
            if session is not None and not session.online and user_id in room.player_ids:
                if not ws_accepted:
                    await ws.accept()
                    ws_accepted = True
                session.mark_online(ws)
                await self._sync_session_to_redis(session)
                # 广播让在线方的前端更新对手状态
                await self.push.broadcast(
                    room_name,
                    protocol.make_player_joined(display_name, room_name, len(room.player_ids)),
                )
                logger.info("WAITING 中玩家重连 [%s] %s(%s)", room_name, display_name, user_id[:8])
                return True

        # ── 场景 1d：RUNNING 中离线玩家极速重连（竞态保护）─────────
        # 问题：on_disconnect() 中，session.mark_offline() 与
        # room 状态机切换到 RECONNECT 之间存在多个 await 点。
        # 若玩家在这个窗口内重连，此时 room.status 仍为 RUNNING，
        # 场景 1（RECONNECT 检查）不会命中，最终落入 is_full → 旁观者分支。
        # 此场景在满员检查之前明确捕获，将该玩家视作重连而非旁观者。
        if room is not None and room.status == RoomStatus.RUNNING:
            session = self.get_session(room_name, user_id)
            if session is not None and not session.online and user_id in room.player_ids:
                if not ws_accepted:
                    await ws.accept()
                    ws_accepted = True
                session.mark_online(ws)
                await self._sync_session_to_redis(session)
                snapshot = await self.snapshot_mgr.load_snapshot(room_name)
                if snapshot:
                    player_view = self.snapshot_mgr.build_player_view(snapshot, user_id)
                    await self.push.unicast(room_name, user_id, player_view)
                    # 若本轮刚结束（未到 match_end），补发轮次结算事件
                    last_round_result = snapshot.get("last_round_result")
                    if last_round_result and not snapshot.get("match_result"):
                        player_result = last_round_result.get(user_id)
                        if player_result:
                            msg = dict(player_result)
                            msg["broadcast"] = False
                            msg["event"] = "round_result_restore"
                            await self.push.unicast(room_name, user_id, msg)
                logger.info("RUNNING 竞态重连 [%s] %s(%s)", room_name, display_name, user_id[:8])
                return True

        # ── 一人一房间限制 ─────────────────────────────────────────
        # 检查玩家是否已在其他房间（含 RECONNECT/ENDED 中的离线玩家）
        active_room = self.get_user_active_room(user_id)
        if active_room is not None and active_room != room_name:
            if not ws_accepted:
                await ws.accept()
            code, reason = WS_CLOSE_ALREADY_IN_ROOM
            await ws.close(code=code, reason=reason)
            logger.info("拒绝连接：玩家 %s 已在房间 [%s]，不能加入 [%s]",
                        user_id[:8], active_room, room_name)
            return False

        # 检查是否已在另一个房间旁观
        spectating_room = self.get_user_spectating_room(user_id)
        if spectating_room is not None and spectating_room != room_name:
            if not ws_accepted:
                await ws.accept()
            code, reason = WS_CLOSE_ALREADY_IN_ROOM
            await ws.close(code=code, reason=reason)
            logger.info("拒绝连接：旁观者 %s 已在房间 [%s]，不能加入 [%s]",
                        user_id[:8], spectating_room, room_name)
            return False

        # ── 场景 2：房间已存在，检查能否加入 ──────────
        if room is not None:
            # 重复 ID 检查须在满员检查之前——防止在线玩家绕过 DUPLICATE_ID 走旁观路径
            if user_id in room.player_ids:
                session = self.get_session(room_name, user_id)
                if session and session.online:
                    if not ws_accepted:
                        await ws.accept()
                    code, reason = WS_CLOSE_DUPLICATE_ID
                    await ws.close(code=code, reason=reason)
                    return False

            # 满员 → 以旁观者身份加入（房间内的现有玩家不受此限制）
            if room.is_full and user_id not in room.player_ids:
                if not ws_accepted:
                    await ws.accept()
                    ws_accepted = True
                await self._join_as_spectator(ws, room, user_id, display_name)
                return True

        # ── 接受连接 ─────────────────────────────────
        if not ws_accepted:
            await ws.accept()

        if room is None:
            # 场景 3：房间不存在 → 创建房间
            await self._create_room(ws, room_name, user_id, display_name, vs_bot, bot_level,
                                     rules=rules, debug_code=debug_code)
        else:
            # 场景 4：房间存在且有空位 → 加入
            await self._join_room(ws, room, user_id, display_name)

        return True

    async def disconnect(
        self, ws: WebSocket, room_name: str, user_id: str
    ) -> None:
        """
        WebSocket 断开时调用。先判断是旁观者还是玩家，分路径处理。
        """
        # 旁观者断线：静默移除，无状态机影响
        if self._get_spectator(room_name, user_id) is not None:
            await self._handle_spectator_disconnect(room_name, user_id)
            return

        # 玩家断线：委托给 ReconnectManager
        session = self.get_session(room_name, user_id)
        if session is None:
            return
        await self.reconnect_mgr.on_disconnect(room_name, user_id, session.connection_id)

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

        # DESTROYED 状态不处理任何 action（cleanup_room 可能还未关闭 WS）
        if room.status == RoomStatus.DESTROYED:
            return

        # 旁观者不允许发送任何 action
        if self._get_spectator(room_name, user_id) is not None:
            await self.push.unicast_spectator(
                room_name, user_id,
                protocol.make_error(ERR_SPECTATOR_ACTION_FORBIDDEN),
            )
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
                # 非房主"返回大厅"：离开房间，房间保留等待新玩家
                # 房主"返回大厅"（异常情况）：内部转为解散房间处理
                await self._handle_leave_ended(room, user_id)
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
        self,
        ws: WebSocket,
        room_name: str,
        user_id: str,
        display_name: str,
        vs_bot: bool = False,
        bot_level: str = "normal",
        rules: dict = None,
        debug_code: int = None,
    ) -> None:
        """创建新房间（[空] → WAITING）"""
        # 清理 Redis 中可能残留的同名孤立数据（服务进程崩溃后可能遗留）。
        # 在写入新房间数据之前调用，确保 Redis 状态干净。
        await self._cleanup_redis(room_name)

        now = time.time()
        room_id = str(uuid.uuid4())

        # vs_bot 房间：把 BOT_ID 直接加入 player_ids，房间立即满员
        player_ids = [user_id, BOT_ID] if vs_bot else [user_id]

        room = Room(
            room_id=room_id,
            room_name=room_name,
            status=RoomStatus.WAITING,
            owner_id=user_id,
            player_ids=player_ids,
            created_at=now,
            updated_at=now,
            expires_at=now + ROOM_MAX_LIFETIME_SEC,
            round_limit=DEFAULT_ROUND_LIMIT,
            vs_bot=vs_bot,
            bot_level=bot_level,
            rules=rules or {},
            debug_code=debug_code,
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

        # vs_bot 房间：额外推送一个 player_joined 事件，让前端知道对手是 CPU
        if vs_bot:
            await self.push.unicast(
                room_name, user_id,
                protocol.make_player_joined("CPU", room_name, 2),
            )

        logger.info("房间创建 [%s] 房主=%s(%s) vs_bot=%s", room_name, display_name, user_id[:8], vs_bot)

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
    # 内部方法：旁观者加入 / 离开
    # ================================================================

    async def _join_as_spectator(
        self, ws: WebSocket, room: Room, user_id: str, display_name: str
    ) -> None:
        """将连接者以旁观者身份加入房间。"""
        room_name = room.room_name

        if room_name not in self.spectators:
            self.spectators[room_name] = {}

        if len(self.spectators[room_name]) >= MAX_SPECTATORS_PER_ROOM:
            code, reason = WS_CLOSE_SPECTATOR_ROOM_FULL
            await ws.close(code=code, reason=reason)
            logger.info("旁观者席位已满 [%s]，拒绝 %s", room_name, user_id[:8])
            return

        spec = SpectatorSession(
            user_id=user_id,
            display_name=display_name,
            room_name=room_name,
            ws=ws,
        )
        self.spectators[room_name][user_id] = spec
        spectator_count = len(self.spectators[room_name])

        # 广播旁观者加入通知（玩家 + 其他旁观者都能看到）
        await self.push.broadcast(
            room_name,
            protocol.make_spectator_joined(display_name, spectator_count),
        )

        # 向新旁观者推送当前游戏状态快照
        snapshot = await self.snapshot_mgr.load_snapshot(room_name)
        if snapshot:
            view = self.snapshot_mgr.build_spectator_view(snapshot)
            await self.push.unicast_spectator(room_name, user_id, view)
        else:
            # 游戏尚未开始（WAITING 状态）
            await self.push.unicast_spectator(room_name, user_id, {
                "broadcast": False,
                "event": "spectator_snapshot",
                "game_status": room.status.value,
                "players": {},
                "wall_count": 0,
            })

        logger.info("旁观者加入 [%s] %s(%s) 共%d名旁观者",
                    room_name, display_name, user_id[:8], spectator_count)

    async def _handle_spectator_disconnect(self, room_name: str, user_id: str) -> None:
        """旁观者断线：静默移除，广播离开通知。"""
        spec = self.spectators.get(room_name, {}).pop(user_id, None)
        if spec is None:
            return

        spectator_count = len(self.spectators.get(room_name, {}))
        await self.push.broadcast(
            room_name,
            protocol.make_spectator_left(spec.display_name, spectator_count),
        )
        logger.info("旁观者离开 [%s] %s(%s) 剩余%d名旁观者",
                    room_name, spec.display_name, user_id[:8], spectator_count)

    # ================================================================
    # 内部方法：房间层 action 处理
    # ================================================================

    async def _handle_start(self, room: Room, user_id: str, card_idx: int | None) -> None:
        """
        WAITING 中处理 start 请求。
        - 人机房间：单人立即开始
        - 双人房间：使用 ReadyService 管理双确认
        """
        room_name = room.room_name

        # vs_bot：单人立即开始，跳过 ReadyService
        if room.vs_bot:
            debug_code = card_idx if card_idx and card_idx > 100 else None
            await self._start_game(room, debug_code)
            return

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
        当前轮结束后（game.status==ENDED），玩家通过 start_new 开始下一轮。
        - 人机房间：单人确认即可开始下一轮
        - 双人房间：双方确认
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

        # vs_bot：单人立即开始下一轮
        if room.vs_bot:
            debug_code = card_idx if card_idx and card_idx > 100 else None
            await self._start_next_round(room, game, debug_code)
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

        # vs_bot：单人决定即可继续
        if not room.vs_bot:
            online_ids = self.push.get_online_user_ids(room_name)
            result = self.end_svc.choose_continue(room_name, user_id, online_ids)
            if not result.all_continue:
                await self.push.broadcast(room_name, protocol.make_continue_vote_changed(
                    continue_user_ids=result.continue_ids,
                    all_continue=False,
                ))
                return

        # 双方（或单人 bot 模式）都选择继续 → 回到 WAITING
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
        """
        ENDED 中处理 end_game（房主解散房间）。
        - 调用方（房主）：收到 room_closed 事件，立即返回大厅。
        - 对手（非房主）：收到 room_dissolved 事件，展示 10 秒倒计时提示框后返回大厅。
        """
        room_name = room.room_name
        session = self.get_session(room_name, user_id)
        display_name = session.display_name if session else user_id

        logger.info("玩家 %s 解散房间 [%s]", display_name, room_name)

        # 向对手发送"房间已解散"通知（含 10 秒倒计时提示框）
        opponent_id = self.push.get_opponent_id(room_name, user_id)
        if opponent_id:
            await self.push.unicast(room_name, opponent_id, protocol.make_room_dissolved())

        # 向调用方发送普通关闭通知，立即返回大厅
        await self.push.unicast(room_name, user_id, protocol.make_room_closed("player_end_game"))

        try:
            await self._do_transition(room, RoomEvent.ANY_END_GAME)
        except InvalidTransitionError:
            pass

        await self.cleanup_room(room_name, room.room_id, "end_game")

    async def _handle_leave_ended(self, room: Room, user_id: str) -> None:
        """
        ENDED 中非房主玩家选择"返回大厅"：
        - 从房间移除该玩家（session + player_ids）
        - 房间回到 WAITING，等待新玩家加入
        - 向房主推送 player_left_ended 通知
        - 关闭该玩家的 WebSocket → 前端自动返回大厅

        若调用方为房主，则转为 end_game 处理（解散房间）。
        """
        room_name = room.room_name
        session = self.get_session(room_name, user_id)
        display_name = session.display_name if session else user_id

        # 房主点了"返回大厅"（正常情况不应发生，按解散处理）
        if user_id == room.owner_id:
            await self._handle_end_game(room, user_id)
            return

        host_id = room.owner_id
        logger.info("非房主玩家 %s 离开 ENDED 房间 [%s]", display_name, room_name)

        # 清除投票状态
        self.end_svc.clear(room_name)
        self.ready_svc.clear(room_name)

        # 从房间移除（player_ids + session）
        self._remove_player_from_room(room_name, user_id)

        # 房间回到 WAITING（复用 BOTH_CONTINUE 转移）
        try:
            await self._do_transition(room, RoomEvent.BOTH_CONTINUE)
        except InvalidTransitionError:
            return

        # 重置比赛状态
        room.round_no = 0
        if room_name in self.games:
            del self.games[room_name]

        await self._sync_room_to_redis(room)

        # 向房主推送通知："xxx 已离开房间"
        await self.push.unicast(room_name, host_id, protocol.make_player_left_ended(display_name))

        # 关闭该玩家连接 → 前端收到 WS close 后返回大厅
        if session and session.ws:
            try:
                await session.ws.close(code=1000, reason="leave_room")
            except Exception:
                pass

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
        # bot 房间中 bot 无 WebSocket，不计入在线数，只需确保真实玩家在线
        online_ids = self.push.get_online_user_ids(room_name)
        min_online = 1 if room.vs_bot else 2
        if len(online_ids) < min_online:
            await self.push.unicast(room_name, user_id,
                                    protocol.make_error(ERR_GAME_PAUSED))
            return

        # DEBUG: 记录收到的 action
        logger.info("[DEBUG] _handle_game_action: room=%s action=%s user=%s card_idx=%s", room_name, action, user_id, card_idx)

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

        # DEBUG: 记录 game.input 返回结果
        logger.info("[DEBUG] game.input result: %s", result)

        # 将 wall_count 注入到结果中（前端需要）
        wall_count = len(game.yama) if hasattr(game, 'yama') else 0

        # 发送结果给各玩家
        for target_id, info in result.items():
            info["broadcast"] = False
            info["wall_count"] = wall_count
            await self.push.unicast(room_name, target_id, info)

        # ── 游戏后续处理 ──────────────────────────
        await self._post_action_bookkeeping(
            room, game, last_result=result if isinstance(result, dict) else None
        )

        # vs_bot：若游戏仍在运行，调度 bot 继续行动
        if room.vs_bot and not game.is_ended:
            self.bot_svc.schedule(room_name)

    async def _post_action_bookkeeping(
        self, room: Room, game: "ChinitsuGame", last_result: dict | None = None
    ) -> None:
        """
        每次游戏层 action 处理完毕后的公共后置逻辑：
        1. 若本轮刚结束，增加轮次计数
        2. 保存快照（若本轮结束且有 last_result，写入 last_round_result 供断线重连恢复）
        3. 若本轮结束，评估比赛是否应该终止
        由 _handle_game_action 和 BotService._run_chain 共同调用。
        """
        room_name = room.room_name
        round_just_ended = game.is_ended

        if round_just_ended:
            room.round_no += 1
            logger.info("第 %d 轮结束 [%s]", room.round_no, room_name)

        # 保存快照，并推送旁观者更新
        snapshot = self.snapshot_mgr.serialize_game(
            game, room_name, room.round_no, room.round_limit,
            display_names=self.get_display_names(room_name),
            owner_id=room.owner_id,
        )
        if round_just_ended and last_result:
            snapshot["last_round_result"] = last_result
        await self.snapshot_mgr.save_snapshot(room_name, snapshot)
        await self._push_spectator_update(room_name, snapshot)

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

        # 确定胜者：积分最高者；若积分相同则 winner_id = None（平局）
        sorted_players = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_players) >= 2 and sorted_players[0][1] != sorted_players[1][1]:
            winner_id = sorted_players[0][0]
        else:
            winner_id = None

        # 广播比赛结束
        await self.push.broadcast(room_name, protocol.make_match_ended(reason, final_scores, winner_id))

        # 将比赛结果写入快照，供断线重连时恢复结算界面
        snapshot["match_result"] = {
            "reason": reason,
            "final_scores": final_scores,
            "winner_id": winner_id,
        }
        await self.snapshot_mgr.save_snapshot(room_name, snapshot)

        logger.info("比赛结束 [%s] 原因=%s 分数=%s", room_name, reason, final_scores)

    # ================================================================
    # 内部方法：游戏启动
    # ================================================================

    async def _start_game(self, room: Room, debug_code: int | None = None) -> None:
        """
        WAITING → RUNNING：创建游戏实例并启动第一轮。
        """
        room_name = room.room_name

        # 创建游戏实例（应用房主规则）
        game = ChinitsuGame(rules=room.rules or None, debug_code=room.debug_code)
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

        # 构建初始游戏状态并发送给双方（bot unicast 静默忽略）
        await self._send_game_start_state(room, game)

        # 保存初始快照，并推送旁观者更新
        snapshot = self.snapshot_mgr.serialize_game(
            game, room_name, room.round_no, room.round_limit,
            display_names=self.get_display_names(room_name),
            owner_id=room.owner_id,
        )
        await self.snapshot_mgr.save_snapshot(room_name, snapshot)
        await self._push_spectator_update(room_name, snapshot)

        # vs_bot：若 bot 是庄家（先行），立即调度 bot
        if room.vs_bot and game.state.current_player == BOT_ID:
            self.bot_svc.schedule(room_name)

        logger.info("游戏开始 [%s] 玩家=%s vs_bot=%s", room_name, room.player_ids, room.vs_bot)

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

        # 保存快照，并推送旁观者更新
        snapshot = self.snapshot_mgr.serialize_game(
            game, room_name, room.round_no, room.round_limit,
            display_names=self.get_display_names(room_name),
            owner_id=room.owner_id,
        )
        await self.snapshot_mgr.save_snapshot(room_name, snapshot)
        await self._push_spectator_update(room_name, snapshot)

        # vs_bot：若 bot 是庄家，调度 bot
        if room.vs_bot and game.state.current_player == BOT_ID:
            self.bot_svc.schedule(room_name)

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

        # DESTROYED 是终态，不写 Redis：cleanup_room 会立即删除该 key。
        # 若提前写入 destroyed 再删除，一旦删除失败就会留下僵尸键。
        if new_status != RoomStatus.DESTROYED:
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

        try:
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
            self.bot_svc.cleanup_room(room_name)
            await self.snapshot_mgr.delete_snapshot(room_name)

            # 清理 Redis
            await self._cleanup_redis(room_name)

        except Exception as e:
            logger.error("cleanup_room 中发生错误 [%s]: %s", room_name, e)

        finally:
            # 内存清理放在 finally 中：即使上方出现异常，也必须清除内存残留，
            # 否则状态为 DESTROYED 的房间会一直占据 self.rooms，导致僵尸房间。
            self.rooms.pop(room_name, None)
            self.sessions.pop(room_name, None)
            self.spectators.pop(room_name, None)
            self.games.pop(room_name, None)

    # ================================================================
    # 辅助方法
    # ================================================================

    def get_session(self, room_name: str, user_id: str) -> PlayerSession | None:
        """获取指定玩家的会话"""
        return self.sessions.get(room_name, {}).get(user_id)

    def get_user_active_room(self, user_id: str) -> str | None:
        """
        返回玩家当前所在的房间名（在线或离线均算）。
        若不在任何房间则返回 None。
        """
        for room_name, room_sessions in self.sessions.items():
            if user_id in room_sessions:
                return room_name
        return None

    def get_user_spectating_room(self, user_id: str) -> str | None:
        """返回用户当前旁观的房间名，若不在任何旁观则返回 None。"""
        for room_name, room_spectators in self.spectators.items():
            if user_id in room_spectators:
                return room_name
        return None

    def _get_spectator(self, room_name: str, user_id: str) -> SpectatorSession | None:
        """获取指定旁观者会话，不存在则返回 None。"""
        return self.spectators.get(room_name, {}).get(user_id)

    async def _push_spectator_update(self, room_name: str, snapshot: dict) -> None:
        """将最新快照以全知视角广播给所有旁观者（游戏动作后调用）。"""
        if not self.spectators.get(room_name):
            return
        view = self.snapshot_mgr.build_spectator_view(snapshot)
        view["event"] = "spectator_game_update"   # 区别于初次加入时的 spectator_snapshot
        await self.push.broadcast_spectators(room_name, view)

    def get_display_names(self, room_name: str) -> dict[str, str]:
        """从 session 中获取房间内所有玩家的昵称映射 {user_id: display_name}"""
        names = {
            uid: s.display_name
            for uid, s in self.sessions.get(room_name, {}).items()
        }
        # vs_bot 房间：补充 bot 的显示名
        room = self.rooms.get(room_name)
        if room and room.vs_bot:
            names[BOT_ID] = "CPU"
        return names

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
            # TTL 为房间最大寿命 + 30 分钟缓冲，作为最后防线：
            # 即使 cleanup_room 完全失败，Redis 也会在此时间后自动删除孤立键。
            await redis.expire(key, ROOM_MAX_LIFETIME_SEC + 30 * 60)
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
            # 从内存中收集玩家 ID（RUNNING 状态下玩家仍在内存中）
            room = self.rooms.get(room_name)
            from_room = set(room.player_ids if room else [])
            from_sessions = set(self.sessions.get(room_name, {}).keys())
            player_ids = from_room | from_sessions

            keys_to_delete: set[str] = {f"room:{room_name}", f"snapshot:{room_name}"}
            for pid in player_ids:
                keys_to_delete.add(f"player_session:{room_name}:{pid}")

            # 扫描 Redis 查找所有属于该房间的 player_session 残留 key。
            # WAITING/ENDED 断线时 _remove_player_from_room() 会提前清空内存，
            # 此时内存已无法提供玩家 ID，靠 SCAN 兜底保证清除完整。
            async for key in redis.scan_iter(f"player_session:{room_name}:*"):
                keys_to_delete.add(key)

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
