# room/reconnect_manager.py — 断线重连管理器
# 职责：
#   1. RUNNING 中玩家断线 → 标记离线、切换 RECONNECT、启动超时计时器
#   2. 断线玩家重连 → 校验身份、恢复在线、取消计时器、推送快照
#   3. 双方同时断线 → 触发房间销毁
#   4. 重连超时 → 在线方判胜，比赛结束

import logging
from typing import TYPE_CHECKING

from room.models import RoomStatus, RoomEvent, RECONNECT_TIMEOUT_SEC
from room import state_machine
from room import protocol
from room.errors import InvalidTransitionError

if TYPE_CHECKING:
    from room.room_manager import RoomManager

logger = logging.getLogger("uvicorn")


class ReconnectManager:
    """
    断线重连管理器。
    不直接持有房间/会话数据，通过 RoomManager 引用访问共享状态。
    """

    def __init__(self, room_manager: "RoomManager"):
        self._rm = room_manager  # 对 RoomManager 的反向引用

    async def on_disconnect(self, room_name: str, user_id: str, connection_id: str) -> None:
        """
        玩家断线时的处理入口。
        由 RoomManager.disconnect() 在确认连接有效后调用。
        """
        room = self._rm.rooms.get(room_name)
        session = self._rm.get_session(room_name, user_id)
        if room is None or session is None:
            return

        # 防止旧连接 disconnect 事件误伤新连接
        if session.connection_id != connection_id:
            logger.debug("忽略旧连接断线事件 [%s/%s]: 旧=%s 新=%s",
                         room_name, user_id, connection_id, session.connection_id)
            return

        if room.status == RoomStatus.RUNNING:
            await self._handle_running_disconnect(room, session)
        elif room.status == RoomStatus.RECONNECT:
            await self._handle_reconnect_disconnect(room, session)
        elif room.status == RoomStatus.WAITING:
            await self._handle_lobby_disconnect(room, session)
        elif room.status == RoomStatus.ENDED:
            await self._handle_ended_disconnect(room, session)

    async def _handle_running_disconnect(self, room, session) -> None:
        """RUNNING 中一方断线"""
        room_name = room.room_name
        user_id = session.user_id

        # 标记离线，同步到 Redis
        session.mark_offline()
        await self._rm._sync_session_to_redis(session)

        # 检查在线人数
        # bot 房间中 bot 无 WebSocket，online_ids 为空仅意味着人类断线，不是双方均离线
        online_ids = self._rm.push.get_online_user_ids(room_name)
        if len(online_ids) == 0 and not room.vs_bot:
            # 双方都断线 → 直接销毁（用 ALL_LEFT，RUNNING 状态无 BOTH_OFFLINE 转移）
            logger.info("双方均断线，销毁房间 [%s]", room_name)
            await self._rm._do_transition(room, RoomEvent.ALL_LEFT)
            await self._rm.cleanup_room(room_name, room.room_id, "both_offline")
            return

        # 单方断线 → 进入 RECONNECT
        try:
            await self._rm._do_transition(room, RoomEvent.PLAYER_DISCONNECT)
        except InvalidTransitionError:
            logger.error("状态转移失败: RUNNING → RECONNECT [%s]", room_name)
            return

        # 保存快照（确保断线前的最新状态，含真实昵称）
        game = self._rm.games.get(room_name)
        if game is not None:
            # 先读取旧快照，保留 last_round_result 等不由 serialize_game 生成的瞬态字段
            old_snapshot = self._rm.snapshot_mgr._memory_store.get(room_name, {})
            snapshot = self._rm.snapshot_mgr.serialize_game(
                game, room_name, room.round_no, room.round_limit,
                display_names=self._rm.get_display_names(room_name),
                owner_id=room.owner_id,
            )
            # serialize_game 不含瞬态结算数据，从旧快照中保留以便重连后恢复 AgariOverlay
            if "last_round_result" in old_snapshot:
                snapshot["last_round_result"] = old_snapshot["last_round_result"]
            await self._rm.snapshot_mgr.save_snapshot(room_name, snapshot)

        # 通知在线方
        opponent_id = self._rm.push.get_opponent_id(room_name, user_id)
        if opponent_id:
            await self._rm.push.unicast(
                room_name, opponent_id, protocol.make_opponent_disconnected()
            )

        # 启动重连超时计时器
        timer_key = f"reconnect:{room_name}:{user_id}"
        await self._rm.timers.schedule(
            timer_key,
            RECONNECT_TIMEOUT_SEC,
            self._on_reconnect_timeout,
            room_name, room.room_id, user_id,
        )
        logger.info("已启动重连计时器 [%s/%s] %ds", room_name, user_id, RECONNECT_TIMEOUT_SEC)

    async def _handle_reconnect_disconnect(self, room, session) -> None:
        """
        RECONNECT 中第二个玩家也断线。
        根据设计文档 v1.1：双方同时断线 → 直接销毁房间。
        """
        room_name = room.room_name
        session.mark_offline()
        await self._rm._sync_session_to_redis(session)

        online_ids = self._rm.push.get_online_user_ids(room_name)
        if len(online_ids) == 0 and not room.vs_bot:
            logger.info("RECONNECT 中双方均断线，销毁房间 [%s]", room_name)
            # 取消所有定时器
            await self._rm.timers.cancel_prefix(f"reconnect:{room_name}:")
            await self._rm._do_transition(room, RoomEvent.BOTH_OFFLINE)
            await self._rm.cleanup_room(room_name, room.room_id, "both_offline")

    async def _handle_lobby_disconnect(self, room, session) -> None:
        """
        WAITING 状态下断线。
        - 房间已满（2 人）：仅标记离线，保留会话，等待重连；清空开始投票。
        - 房间未满（1 人）：移除玩家；若房间为空则销毁。
        注意：vs_bot 房间的 player_ids 含 BOT_ID（无 WS），get_online_user_ids 永远
        不计 bot，因此人类断线后 online_ids == 0，但不应视为「双方均离线」而销毁房间。
        """
        room_name = room.room_name
        user_id = session.user_id
        display_name = session.display_name

        if len(room.player_ids) == 2:
            # 双方已就位：保留会话，仅标记离线（等待重连）
            session.mark_offline()
            await self._rm._sync_session_to_redis(session)
            # 开始投票需清空（断线方无法保持 ready 状态）
            self._rm.ready_svc.clear(room_name)

            online_ids = self._rm.push.get_online_user_ids(room_name)
            if len(online_ids) == 0 and not room.vs_bot:
                # 真实双人房间双方均离线 → 销毁
                await self._rm._do_transition(room, RoomEvent.ALL_LEFT)
                await self._rm.cleanup_room(room_name, room.room_id, "all_left")
            elif len(online_ids) > 0:
                # 仍有真实玩家在线 → 通知对方
                await self._rm.push.broadcast(
                    room_name,
                    protocol.make_player_left(display_name, room_name, len(room.player_ids)),
                )
            # else: vs_bot 且人类已离线，保留房间静默等待人类重连
        else:
            # 房间只有 1 人：直接移除
            self._rm._remove_player_from_room(room_name, user_id)
            self._rm.ready_svc.clear(room_name)
            if len(room.player_ids) == 0:
                await self._rm._do_transition(room, RoomEvent.ALL_LEFT)
                await self._rm.cleanup_room(room_name, room.room_id, "all_left")

    async def _handle_ended_disconnect(self, room, session) -> None:
        """
        ENDED 状态下断线：保留会话，仅标记离线。
        玩家仍留在房间中，重连后可继续对 continue/end 投票。
        不清空已有投票记录。
        若双方均已断线，销毁房间（同 WAITING/RECONNECT 的处理逻辑）：
        - 保留 ENDED 房间的意义是允许意外断线的玩家重连后继续投票；
        - 若双方均已离线，说明双方都主动离开，无需保留旧 ENDED 状态，
          下次进入同名房间时应创建全新房间，而非重连旧对局结算界面。
        """
        room_name = room.room_name
        session.mark_offline()
        await self._rm._sync_session_to_redis(session)
        logger.info("ENDED 中玩家断线，保留会话 [%s/%s]", room_name, session.user_id)

        # 若所有真实玩家均已离线 → 销毁房间，避免下次同名连接误入旧 ENDED 房间。
        # vs_bot 房间：bot 无 WS，online_ids 永远不含 bot，不应误判为「双方均离线」。
        online_ids = self._rm.push.get_online_user_ids(room_name)
        if len(online_ids) == 0 and not room.vs_bot:
            logger.info("ENDED 中双方均断线，销毁房间 [%s]", room_name)
            await self._rm._do_transition(room, RoomEvent.ALL_LEFT)
            await self._rm.cleanup_room(room_name, room.room_id, "all_left_ended")

    async def on_reconnect(self, ws, room_name: str, user_id: str, display_name: str) -> bool:
        """
        玩家重连处理。
        返回 True 表示重连成功，False 表示重连失败（身份不匹配等）。
        """
        room = self._rm.rooms.get(room_name)
        session = self._rm.get_session(room_name, user_id)

        if room is None or session is None:
            return False

        if room.status != RoomStatus.RECONNECT:
            return False

        # 校验：该玩家必须属于此房间且当前离线
        if user_id not in room.player_ids:
            return False
        if session.online:
            return False  # 已在线，不是重连

        # 恢复在线状态，同步到 Redis
        import uuid
        new_conn_id = str(uuid.uuid4())
        session.mark_online(ws, new_conn_id)
        await self._rm._sync_session_to_redis(session)

        # 取消重连计时器
        timer_key = f"reconnect:{room_name}:{user_id}"
        await self._rm.timers.cancel(timer_key)

        # 状态转移：RECONNECT → RUNNING
        try:
            await self._rm._do_transition(room, RoomEvent.PLAYER_RECONNECT)
        except InvalidTransitionError:
            logger.error("状态转移失败: RECONNECT → RUNNING [%s]", room_name)
            return False

        # 推送快照给重连玩家
        snapshot = await self._rm.snapshot_mgr.load_snapshot(room_name)
        if snapshot:
            player_view = self._rm.snapshot_mgr.build_player_view(snapshot, user_id)
            await self._rm.push.unicast(room_name, user_id, player_view)
            # 若本轮刚结束（未到 match_end），补发轮次结算事件让前端恢复 AgariOverlay
            last_round_result = snapshot.get("last_round_result")
            if last_round_result and not snapshot.get("match_result"):
                player_result = last_round_result.get(user_id)
                if player_result:
                    msg = dict(player_result)
                    msg["broadcast"] = False
                    msg["event"] = "round_result_restore"
                    await self._rm.push.unicast(room_name, user_id, msg)

        # 通知对手：对手已重连
        opponent_id = self._rm.push.get_opponent_id(room_name, user_id)
        if opponent_id:
            await self._rm.push.unicast(
                room_name, opponent_id, protocol.make_opponent_reconnected()
            )

        # bot 房间：重连后恢复 bot 行动链（若当前轮到 bot）
        if room.vs_bot:
            self._rm.bot_svc.schedule(room_name)

        logger.info("重连成功 [%s/%s]", room_name, user_id)
        return True

    async def _on_reconnect_timeout(self, room_name: str, room_id: str, user_id: str) -> None:
        """
        重连超时回调。120 秒内未重连 → 比赛结束，在线方判胜。
        """
        room = self._rm.rooms.get(room_name)
        if room is None:
            return  # 房间已销毁
        if room.room_id != room_id:
            return  # room_id 不匹配（旧 timer 误触发）
        if room.status != RoomStatus.RECONNECT:
            return  # 状态已变（可能已重连或已销毁）

        # 确认该玩家仍然离线
        session = self._rm.get_session(room_name, user_id)
        if session is None or session.online:
            return

        logger.info("重连超时 [%s/%s]，在线方判胜", room_name, user_id)

        # 找到在线方
        online_ids = self._rm.push.get_online_user_ids(room_name)
        winner_id = online_ids[0] if online_ids else None

        # 状态转移：RECONNECT → ENDED
        try:
            await self._rm._do_transition(room, RoomEvent.RECONNECT_TIMEOUT)
        except InvalidTransitionError:
            return

        # 广播超时判负结果
        await self._rm.push.broadcast(
            room_name,
            protocol.make_reconnect_timeout(
                winner_id=winner_id or "",
                loser_id=user_id,
            ),
        )
