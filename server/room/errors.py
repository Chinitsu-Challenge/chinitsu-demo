# room/errors.py — 房间模块错误码与异常定义
# 所有房间层返回给客户端的错误码统一在此管理，防止魔法字符串散落
#
# 命名规则：
#   WS_CLOSE_*  WebSocket 关闭码（code, reason），用于强制断开连接
#   ERR_*       JSON 业务错误码（字符串），游戏进行中以 JSON 消息返回，不关闭连接


# ── WebSocket 关闭码 ──────────────────────────────────────────
# code 1001: 服务端主动关闭（房间销毁）
WS_CLOSE_ROOM_EXPIRED    = (1001, "room_expired")       # 房间 40 分钟到期
WS_CLOSE_ROOM_CLOSED     = (1001, "room_closed")        # 房间被关闭（end_game / 双方断线）

# code 1003: 连接被拒绝（客户端操作不合法）
WS_CLOSE_ROOM_FULL            = (1003, "room_full")             # 房间玩家已满（2 人，且不允许旁观）
WS_CLOSE_DUPLICATE_ID         = (1003, "duplicate_id")          # 同一 user_id 已在线
WS_CLOSE_INVALID_ROOM         = (1003, "invalid_room_name")     # 房间名不合法
WS_CLOSE_ALREADY_IN_ROOM      = (1003, "already_in_room")       # 玩家已在另一个房间中
WS_CLOSE_SPECTATOR_ROOM_FULL  = (1003, "spectator_room_full")   # 旁观者席位已满（上限 10）

# code 1008: 策略违反（认证失败）
WS_CLOSE_INVALID_TOKEN   = (1008, "invalid_token")      # JWT 无效


# ── JSON 业务错误码 ────────────────────────────────────────────
# 游戏进行中以 {"event": "error", "code": "..."} 消息返回，不关闭连接

# 状态类：请求与当前房间/游戏状态不符
ERR_GAME_NOT_STARTED  = "game_not_started"      # WAITING 中发送了游戏动作
ERR_GAME_PAUSED       = "game_paused"           # RECONNECT 中发送了游戏动作
ERR_GAME_ENDED        = "game_ended"            # ENDED 中发送了非法动作
ERR_ROUND_NOT_ENDED   = "round_not_ended"       # 当前轮次尚未结束

# 人员类
ERR_NOT_ENOUGH_PLAYERS = "not_enough_players"   # 不足 2 人无法开始

# 操作类
ERR_UNKNOWN_ACTION              = "unknown_action"               # 未知的 action 类型
ERR_SPECTATOR_ACTION_FORBIDDEN  = "spectator_action_forbidden"   # 旁观者不能发送游戏动作


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
