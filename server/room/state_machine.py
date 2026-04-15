# room/state_machine.py — 房间级状态机
# 纯函数实现，不持有状态、不产生副作用。
# 输入：当前状态 + 事件 → 输出：目标状态（或抛出 InvalidTransitionError）

from room.models import RoomStatus, RoomEvent
from room.errors import InvalidTransitionError

# ── 合法状态转换表 ──────────────────────────────────────────────
# key = (当前状态, 事件)   value = 目标状态
_TRANSITIONS: dict[tuple[RoomStatus, RoomEvent], RoomStatus] = {
    # [空] → WAITING：由 RoomManager 在创建时直接设置，不经过状态机

    # WAITING：等待双方确认开始
    (RoomStatus.WAITING, RoomEvent.BOTH_READY):        RoomStatus.RUNNING,
    (RoomStatus.WAITING, RoomEvent.ALL_LEFT):           RoomStatus.DESTROYED,
    (RoomStatus.WAITING, RoomEvent.ROOM_EXPIRED):       RoomStatus.DESTROYED,

    # RUNNING：对局进行中
    (RoomStatus.RUNNING, RoomEvent.PLAYER_DISCONNECT):  RoomStatus.RECONNECT,
    (RoomStatus.RUNNING, RoomEvent.MATCH_END):          RoomStatus.ENDED,
    (RoomStatus.RUNNING, RoomEvent.ROOM_EXPIRED):       RoomStatus.DESTROYED,
    (RoomStatus.RUNNING, RoomEvent.ALL_LEFT):           RoomStatus.DESTROYED,

    # RECONNECT：一方断线等待重连
    (RoomStatus.RECONNECT, RoomEvent.PLAYER_RECONNECT): RoomStatus.RUNNING,
    (RoomStatus.RECONNECT, RoomEvent.RECONNECT_TIMEOUT): RoomStatus.ENDED,
    (RoomStatus.RECONNECT, RoomEvent.BOTH_OFFLINE):     RoomStatus.DESTROYED,
    (RoomStatus.RECONNECT, RoomEvent.ROOM_EXPIRED):     RoomStatus.DESTROYED,
    (RoomStatus.RECONNECT, RoomEvent.ALL_LEFT):         RoomStatus.DESTROYED,

    # ENDED：比赛结束，等待决策
    (RoomStatus.ENDED, RoomEvent.BOTH_CONTINUE):        RoomStatus.WAITING,
    (RoomStatus.ENDED, RoomEvent.ANY_END_GAME):         RoomStatus.DESTROYED,
    (RoomStatus.ENDED, RoomEvent.ROOM_EXPIRED):         RoomStatus.DESTROYED,
    (RoomStatus.ENDED, RoomEvent.ALL_LEFT):             RoomStatus.DESTROYED,
}


def can_transition(current: RoomStatus, event: RoomEvent) -> bool:
    """检查状态转移是否合法"""
    return (current, event) in _TRANSITIONS


def transition(current: RoomStatus, event: RoomEvent) -> RoomStatus:
    """
    执行状态转移。
    合法 → 返回目标状态
    非法 → 抛出 InvalidTransitionError
    """
    target = _TRANSITIONS.get((current, event))
    if target is None:
        raise InvalidTransitionError(current.value, event.value)
    return target
