# room/chat_handler.py — 聊天与表情处理
# 纯函数模块，不依赖 RoomManager 内部状态，通过参数注入 push 和 sessions。

from typing import TYPE_CHECKING

from room import protocol

if TYPE_CHECKING:
    from room.push_service import PushService
    from room.models import PlayerSession

CHAT_MAX_LEN = 100

EMOTE_ALLOWLIST = {"thumbsup", "lol", "wow", "sorry", "skull", "think", "gg"}


def _display_name(sessions: dict, user_id: str) -> str:
    session = sessions.get(user_id)
    return session.display_name if session else user_id


async def handle_chat(
    push: "PushService",
    sessions: "dict[str, PlayerSession]",
    room_name: str,
    user_id: str,
    text: str,
) -> None:
    text = text.strip()[:CHAT_MAX_LEN]
    if not text:
        return
    name = _display_name(sessions, user_id)
    await push.broadcast(room_name, protocol.make_chat(name, text))


async def handle_emote(
    push: "PushService",
    sessions: "dict[str, PlayerSession]",
    room_name: str,
    user_id: str,
    emote_id: str,
) -> None:
    if emote_id not in EMOTE_ALLOWLIST:
        return
    name = _display_name(sessions, user_id)
    await push.broadcast(room_name, protocol.make_emote(name, emote_id))
