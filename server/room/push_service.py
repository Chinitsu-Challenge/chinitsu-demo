# room/push_service.py — WebSocket 推送服务
# 封装所有 WebSocket 发送操作，屏蔽底层连接细节。
# 提供广播（房间内所有在线玩家）和单播（指定玩家）两种模式。

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from room.models import PlayerSession

logger = logging.getLogger("uvicorn")


class PushService:
    """
    推送服务：通过 PlayerSession 中的 ws 引用发送 JSON 消息。
    所有房间级主动推送都通过此服务发出。
    """

    def __init__(self, sessions_store: dict[str, dict[str, "PlayerSession"]]):
        """
        sessions_store: room_name -> {user_id -> PlayerSession} 的全局引用
        由 RoomManager 在初始化时传入。
        """
        self._sessions = sessions_store

    async def unicast(self, room_name: str, user_id: str, payload: dict) -> bool:
        """
        单播：向指定房间中的指定玩家发送消息。
        返回 True 表示发送成功，False 表示玩家不在线或发送失败。
        """
        session = self._get_session(room_name, user_id)
        if session is None or not session.online or session.ws is None:
            return False
        try:
            await session.ws.send_json(payload)
            return True
        except Exception as e:
            logger.warning("Unicast failed [%s/%s]: %s", room_name, user_id, e)
            return False

    async def broadcast(self, room_name: str, payload: dict, exclude: str | None = None) -> int:
        """
        广播：向房间内所有在线玩家发送消息。
        exclude: 可选，排除指定 user_id（例如不通知自己）。
        返回成功发送的人数。
        """
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
                    logger.warning("Broadcast failed [%s/%s]: %s", room_name, uid, e)
        return sent

    async def close_all_connections(self, room_name: str, code: int = 1001, reason: str = ""):
        """
        关闭房间内所有 WebSocket 连接。
        用于房间销毁、房间到期等场景。
        """
        room_sessions = self._sessions.get(room_name, {})
        for uid, session in room_sessions.items():
            if session.ws is not None:
                try:
                    await session.ws.close(code=code, reason=reason)
                except Exception:
                    pass  # 连接可能已断开，静默处理
                session.ws = None

    def _get_session(self, room_name: str, user_id: str) -> "PlayerSession | None":
        """获取指定玩家的会话"""
        return self._sessions.get(room_name, {}).get(user_id)

    def get_online_user_ids(self, room_name: str) -> list[str]:
        """获取房间内所有在线玩家 ID"""
        room_sessions = self._sessions.get(room_name, {})
        return [uid for uid, s in room_sessions.items() if s.online and s.ws is not None]

    def get_opponent_id(self, room_name: str, user_id: str) -> str | None:
        """获取对手的 user_id"""
        room_sessions = self._sessions.get(room_name, {})
        for uid in room_sessions:
            if uid != user_id:
                return uid
        return None
