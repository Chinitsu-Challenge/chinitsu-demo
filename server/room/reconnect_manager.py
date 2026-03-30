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
        elif room.status in (RoomStatus.WAITING, RoomStatus.ENDED):
            await self._handle_lobby_disconnect(room, session)

    async def _handle_running_disconnect(self, room, session) -> None:
        """RUNNING 中一方断线"""
        room_name = room.room_name
        user_id = session.user_id

        # 标记离线
        session.mark_offline()

        # 检查在线人数
        online_ids = self._rm.push.get_online_user_ids(room_name)
        if len(online_ids) == 0:
            # 双方都断线 → 直接销毁
            logger.info("双方均断线，销毁房间 [%s]", room_name)
            await self._rm._do_transition(room, RoomEvent.BOTH_OFFLINE)
            await self._rm.cleanup_room(room_name, room.room_id, "both_offline")
            return

        # 单方断线 → 进入 RECONNECT
        try:
            await self._rm._do_transition(room, RoomEvent.PLAYER_DISCONNECT)
        except InvalidTransitionError:
            logger.error("状态转移失败: RUNNING → RECONNECT [%s]", room_name)
            return

        # 保存快照（确保断线前的最新状态）
        game = self._rm.games.get(room_name)
        if game is not None:
            snapshot = self._rm.snapshot_mgr.serialize_game(
                game, room_name, room.round_no, room.round_limit
            )
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

        online_ids = self._rm.push.get_online_user_ids(room_name)
        if len(online_ids) == 0:
            logger.info("RECONNECT 中双方均断线，销毁房间 [%s]", room_name)
            # 取消所有定时器
            await self._rm.timers.cancel_prefix(f"reconnect:{room_name}")
            await self._rm._do_transition(room, RoomEvent.BOTH_OFFLINE)
            await self._rm.cleanup_room(room_name, room.room_id, "both_offline")

    async def _handle_lobby_disconnect(self, room, session) -> None:
        """
        WAITING / ENDED 状态下断线：直接移除玩家，不进重连。
        """
        room_name = room.room_name
        user_id = session.user_id
        display_name = session.display_name

        # 从房间中移除玩家
        self._rm._remove_player_from_room(room_name, user_id)

        # 清空投票状态（人员变动后投票无效）
        self._rm.ready_svc.clear(room_name)
        self._rm.end_svc.clear(room_name)

        # 检查房间是否为空
        if len(room.player_ids) == 0:
            await self._rm._do_transition(room, RoomEvent.ALL_LEFT)
            await self._rm.cleanup_room(room_name, room.room_id, "all_left")
        else:
            # 通知剩余玩家
            remaining_count = len(room.player_ids)
            await self._rm.push.broadcast(
                room_name,
                protocol.make_player_left(display_name, room_name, remaining_count),
            )

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

        # 恢复在线状态
        import uuid
        new_conn_id = str(uuid.uuid4())
        session.mark_online(ws, new_conn_id)

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

        # 通知对手：对手已重连
        opponent_id = self._rm.push.get_opponent_id(room_name, user_id)
        if opponent_id:
            await self._rm.push.unicast(
                room_name, opponent_id, protocol.make_opponent_reconnected()
            )

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
