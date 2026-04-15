# room/push_service.py — WebSocket 推送服务
# 封装所有 WebSocket 发送操作，屏蔽底层连接细节。
# 提供广播和单播两种模式，同时覆盖玩家和旁观者。
#
# 方法速查：
#   unicast(room, uid, payload)            → 单播给指定玩家
#   unicast_spectator(room, uid, payload)  → 单播给指定旁观者
#   broadcast(room, payload, exclude)      → 广播给所有玩家 + 旁观者（房间内所有人）
#   broadcast_players(room, payload)       → 仅广播给玩家
#   broadcast_spectators(room, payload)    → 仅广播给旁观者
#   close_all_connections(room, code, reason) → 关闭所有连接（玩家 + 旁观者）

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from room.models import PlayerSession, SpectatorSession

logger = logging.getLogger("uvicorn")


class PushService:
    """
    推送服务：通过 PlayerSession / SpectatorSession 中的 ws 引用发送 JSON 消息。
    所有房间级主动推送都通过此服务发出。
    """

    def __init__(
        self,
        sessions_store: dict[str, dict[str, "PlayerSession"]],
        spectators_store: dict[str, dict[str, "SpectatorSession"]],
    ):
        """
        sessions_store:   room_name -> {user_id -> PlayerSession}
        spectators_store: room_name -> {user_id -> SpectatorSession}
        两者均为 RoomManager 持有的全局字典引用。
        """
        self._sessions = sessions_store
        self._spectators = spectators_store

    # ── 单播 ────────────────────────────────────────────────────

    async def unicast(self, room_name: str, user_id: str, payload: dict) -> bool:
        """单播：向指定玩家发送消息。"""
        session = self._sessions.get(room_name, {}).get(user_id)
        if session is None or not session.online or session.ws is None:
            return False
        try:
            await session.ws.send_json(payload)
            return True
        except Exception as e:
            logger.warning("Unicast failed [%s/%s]: %s", room_name, user_id, e)
            return False

    async def unicast_spectator(self, room_name: str, user_id: str, payload: dict) -> bool:
        """单播：向指定旁观者发送消息。"""
        spec = self._spectators.get(room_name, {}).get(user_id)
        if spec is None or spec.ws is None:
            return False
        try:
            await spec.ws.send_json(payload)
            return True
        except Exception as e:
            logger.warning("Spectator unicast failed [%s/%s]: %s", room_name, user_id, e)
            return False

    # ── 广播 ────────────────────────────────────────────────────

    async def broadcast(
        self, room_name: str, payload: dict, exclude: str | None = None
    ) -> int:
        """
        广播：向房间内所有在线玩家 + 所有旁观者发送消息。
        exclude: 可排除指定 user_id（仅对玩家生效，旁观者不受影响）。
        返回成功发送的总人数。
        """
        sent = await self.broadcast_players(room_name, payload, exclude=exclude)
        sent += await self.broadcast_spectators(room_name, payload)
        return sent

    async def broadcast_players(
        self, room_name: str, payload: dict, exclude: str | None = None
    ) -> int:
        """仅广播给玩家（旁观者不收）。"""
        room_sessions = self._sessions.get(room_name, {})
        sent = 0
        for uid, session in room_sessions.items():
            if uid == exclude:
                continue
            if session.online and session.ws is not None:
                try:
                    await session.ws.send_json(payload)
                    sent += 1
                except Exception as e:
                    logger.warning("Broadcast(players) failed [%s/%s]: %s", room_name, uid, e)
        return sent

    async def broadcast_spectators(self, room_name: str, payload: dict) -> int:
        """仅广播给旁观者（玩家不收）。"""
        room_spectators = self._spectators.get(room_name, {})
        sent = 0
        for uid, spec in room_spectators.items():
            if spec.ws is not None:
                try:
                    await spec.ws.send_json(payload)
                    sent += 1
                except Exception as e:
                    logger.warning("Broadcast(spectators) failed [%s/%s]: %s", room_name, uid, e)
        return sent

    # ── 关闭连接 ─────────────────────────────────────────────────

    async def close_all_connections(
        self, room_name: str, code: int = 1001, reason: str = ""
    ) -> None:
        """关闭房间内所有 WebSocket 连接（玩家 + 旁观者）。"""
        for uid, session in self._sessions.get(room_name, {}).items():
            if session.ws is not None:
                try:
                    await session.ws.close(code=code, reason=reason)
                except Exception:
                    pass
                session.ws = None

        for uid, spec in self._spectators.get(room_name, {}).items():
            if spec.ws is not None:
                try:
                    await spec.ws.close(code=code, reason=reason)
                except Exception:
                    pass
                spec.ws = None

    # ── 查询工具 ─────────────────────────────────────────────────

    def get_online_user_ids(self, room_name: str) -> list[str]:
        """获取房间内所有在线玩家 ID（不含旁观者）。"""
        room_sessions = self._sessions.get(room_name, {})
        return [uid for uid, s in room_sessions.items() if s.online and s.ws is not None]

    def get_opponent_id(self, room_name: str, user_id: str) -> str | None:
        """获取对手的 user_id（仅玩家间）。"""
        for uid in self._sessions.get(room_name, {}):
            if uid != user_id:
                return uid
        return None

    def get_spectator_count(self, room_name: str) -> int:
        """获取当前旁观者人数。"""
        return len(self._spectators.get(room_name, {}))
