# room/errors.py — 房间模块错误码与异常定义
# 所有房间层返回给客户端的错误码统一在此管理，防止魔法字符串散落


# ── WebSocket 关闭码 ──────────────────────────────────────────
# 这些错误在 WebSocket 握手阶段或需要强制关闭连接时使用

WS_CLOSE_ROOM_FULL = (1003, "room_full")              # 房间已满（2 人）
WS_CLOSE_DUPLICATE_ID = (1003, "duplicate_id")         # 同一 user_id 已在线
WS_CLOSE_INVALID_TOKEN = (1008, "invalid_token")       # JWT 无效
WS_CLOSE_INVALID_ROOM = (1003, "invalid_room_name")    # 房间名不合法
WS_CLOSE_ROOM_EXPIRED = (1001, "room_expired")         # 房间 40 分钟到期
WS_CLOSE_ROOM_CLOSED = (1001, "room_closed")           # 房间被关闭（end_game / 双方断线）


# ── JSON 业务错误码 ────────────────────────────────────────────
# 这些错误在游戏进行中作为 JSON 消息返回，不关闭连接

ERR_GAME_NOT_STARTED = "game_not_started"       # WAITING 中发送了游戏动作
ERR_GAME_PAUSED = "game_paused"                 # RECONNECT 中发送了游戏动作
ERR_GAME_ENDED = "game_ended"                   # ENDED 中发送了非法动作
ERR_NOT_ENOUGH_PLAYERS = "not_enough_players"   # 不足 2 人无法开始
ERR_ALREADY_READY = "already_ready"             # 重复点击 start
ERR_INVALID_ACTION = "invalid_action_for_state" # 当前状态不允许该操作
ERR_UNKNOWN_ACTION = "unknown_action"           # 未知的 action 类型
ERR_ROOM_EXPIRED = "room_expired"               # 房间已到期
ERR_ROOM_CLOSED = "room_closed"                 # 房间已关闭
ERR_ROUND_NOT_ENDED = "round_not_ended"         # 当前轮次尚未结束，不能 start_new


# ── 异常类 ──────────────────────────────────────────────────────

class RoomError(Exception):
    """房间模块通用异常基类"""
    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class InvalidTransitionError(RoomError):
    """非法状态转移"""
    def __init__(self, current_status: str, event: str):
        super().__init__(
            code="invalid_transition",
            message=f"Cannot transition from '{current_status}' via event '{event}'"
        )
        self.current_status = current_status
        self.event = event
