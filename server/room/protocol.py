# room/protocol.py — 推送消息 payload 构造函数
# 纯函数，不依赖 WebSocket，只负责生成标准格式的消息字典。
# 所有服务端主动推送的消息格式统一在此定义。


def make_error(code: str, message: str = "") -> dict:
    """构造错误响应"""
    return {
        "broadcast": False,
        "event": "error",
        "code": code,
        "message": message or code,
    }


# ── 房间类事件 ──────────────────────────────────────────────────

def make_player_joined(display_name: str, room_name: str, player_count: int) -> dict:
    """玩家加入房间通知（广播）"""
    return {
        "broadcast": True,
        "event": "player_joined",
        "display_name": display_name,
        "room_name": room_name,
        "player_count": player_count,
    }


def make_player_left(display_name: str, room_name: str, player_count: int) -> dict:
    """玩家离开房间通知（广播）"""
    return {
        "broadcast": True,
        "event": "player_left",
        "display_name": display_name,
        "room_name": room_name,
        "player_count": player_count,
    }


def make_start_ready_changed(ready_user_ids: list[str], all_ready: bool) -> dict:
    """准备状态变更通知（广播）"""
    return {
        "broadcast": True,
        "event": "start_ready_changed",
        "ready_user_ids": ready_user_ids,
        "all_ready": all_ready,
    }


def make_continue_vote_changed(continue_user_ids: list[str], all_continue: bool) -> dict:
    """继续投票状态变更通知（广播）"""
    return {
        "broadcast": True,
        "event": "continue_vote_changed",
        "continue_user_ids": continue_user_ids,
        "all_continue": all_continue,
    }


def make_room_expired(room_name: str) -> dict:
    """房间到期通知（广播）"""
    return {
        "broadcast": True,
        "event": "room_expired",
        "room_name": room_name,
    }


def make_room_closed(reason: str) -> dict:
    """房间关闭通知（广播）"""
    return {
        "broadcast": True,
        "event": "room_closed",
        "reason": reason,
    }


def make_match_ended(reason: str, final_scores: dict[str, int], winner_id: str | None) -> dict:
    """比赛结束通知（广播），附带最终分数与胜者 ID（平局时为 None）"""
    return {
        "broadcast": True,
        "event": "match_ended",
        "reason": reason,
        "final_scores": final_scores,
        "winner_id": winner_id,
    }


# ── 重连类事件 ──────────────────────────────────────────────────

def make_opponent_disconnected() -> dict:
    """对手断线通知（单播给在线方）"""
    return {
        "broadcast": False,
        "event": "opponent_disconnected",
    }


def make_opponent_reconnected() -> dict:
    """对手重连通知（单播给在线方）"""
    return {
        "broadcast": False,
        "event": "opponent_reconnected",
    }


def make_reconnect_timeout(winner_id: str, loser_id: str) -> dict:
    """重连超时判负通知（广播）"""
    return {
        "broadcast": True,
        "event": "reconnect_timeout",
        "winner_id": winner_id,
        "loser_id": loser_id,
    }


# ── 聊天 / 表情 ──────────────────────────────────────────────────

def make_chat(display_name: str, text: str) -> dict:
    """聊天消息（广播）"""
    return {
        "broadcast": True,
        "event": "chat",
        "display_name": display_name,
        "text": text,
    }


def make_emote(display_name: str, emote_id: str) -> dict:
    """表情包消息（广播）"""
    return {
        "broadcast": True,
        "event": "emote",
        "display_name": display_name,
        "emote_id": emote_id,
    }


# ── 超时类事件 ──────────────────────────────────────────────────

def make_timeout_warning(seconds_left: int) -> dict:
    """操作超时提醒（单播）"""
    return {
        "broadcast": False,
        "event": "timeout_warning",
        "seconds_left": seconds_left,
    }


def make_auto_action(action: str) -> dict:
    """超时自动操作通知（单播）"""
    return {
        "broadcast": False,
        "event": "auto_action",
        "action": action,
    }


# ── ENDED 阶段离开类事件 ────────────────────────────────────────

def make_room_dissolved() -> dict:
    """
    房主解散房间通知（单播给对手）。
    frontend: 对手收到后展示 10 秒倒计时提示框，到期自动返回大厅。
    """
    return {
        "broadcast": True,
        "event": "room_dissolved",
    }


def make_player_left_ended(display_name: str) -> dict:
    """
    非房主玩家在 ENDED 状态选择"返回大厅"后，通知房主的单播消息。
    frontend: 房主收到后展示小型提示框"xxx 已离开房间"，10 秒后自动消失。
    """
    return {
        "broadcast": False,
        "event": "player_left_ended",
        "display_name": display_name,
    }


# ── 旁观者类事件 ────────────────────────────────────────────────

def make_spectator_joined(display_name: str, spectator_count: int) -> dict:
    """旁观者加入通知（广播给房间内所有人）"""
    return {
        "broadcast": True,
        "event": "spectator_joined",
        "display_name": display_name,
        "spectator_count": spectator_count,
    }


def make_spectator_left(display_name: str, spectator_count: int) -> dict:
    """旁观者离开通知（广播给房间内所有人）"""
    return {
        "broadcast": True,
        "event": "spectator_left",
        "display_name": display_name,
        "spectator_count": spectator_count,
    }
