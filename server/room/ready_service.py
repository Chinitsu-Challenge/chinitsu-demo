# room/ready_service.py — WAITING 阶段开始确认服务
# 管理 WAITING 状态下的 "start" 双确认流程。
# 两名在线玩家都发送 start 后，才触发 BOTH_READY 事件。

import logging

logger = logging.getLogger("uvicorn")


class ReadyResult:
    """mark_ready 的返回结果"""
    def __init__(self, all_ready: bool, ready_ids: list[str], debug_code: int | None = None):
        self.all_ready = all_ready       # 是否双方都已 ready
        self.ready_ids = ready_ids       # 当前已 ready 的玩家列表
        self.debug_code = debug_code     # 调试代码（如有）


class ReadyService:
    """
    WAITING 阶段与 RUNNING 中轮次间重启的开始确认。
    - start：标记一名玩家已准备
    - cancel_start：取消准备
    - 当两名在线玩家都 ready 时返回 all_ready=True
    - 幂等：重复 start 不会多次计票
    """

    def __init__(self):
        # room_name -> {user_id: card_idx}
        # card_idx 保留用于传递 debug_code
        self._ready: dict[str, dict[str, int | None]] = {}

    def mark_ready(
        self,
        room_name: str,
        user_id: str,
        online_user_ids: list[str],
        card_idx: int | None = None,
    ) -> ReadyResult:
        """
        标记玩家已准备。
        online_user_ids: 当前房间内在线玩家列表（由 RoomManager 提供）。
        card_idx: 若 >100 则视为 debug_code。
        返回 ReadyResult，由调用方决定是否触发 BOTH_READY。
        """
        if room_name not in self._ready:
            self._ready[room_name] = {}

        # 幂等：已 ready 的玩家不重复记录
        self._ready[room_name][user_id] = card_idx

        # 检查是否所有在线玩家都已 ready
        ready_set = set(self._ready[room_name].keys())
        online_set = set(online_user_ids)
        all_ready = len(online_set) >= 2 and online_set.issubset(ready_set)

        # 提取 debug_code（任意一方提供即可）
        debug_code = None
        for uid, cidx in self._ready[room_name].items():
            if cidx is not None and cidx > 100:
                debug_code = cidx
                break

        return ReadyResult(
            all_ready=all_ready,
            ready_ids=list(ready_set & online_set),
            debug_code=debug_code,
        )

    def cancel_ready(self, room_name: str, user_id: str) -> list[str]:
        """
        取消玩家的准备状态。
        返回当前仍处于 ready 的玩家列表。
        """
        if room_name in self._ready:
            self._ready[room_name].pop(user_id, None)
        return list(self._ready.get(room_name, {}).keys())

    def clear(self, room_name: str) -> None:
        """
        清空房间的所有 ready 状态。
        触发时机：
        - 游戏成功开始后
        - 玩家离开导致人数不足
        - 房间状态切换时
        """
        self._ready.pop(room_name, None)

    def get_ready_ids(self, room_name: str) -> list[str]:
        """获取当前已 ready 的玩家列表"""
        return list(self._ready.get(room_name, {}).keys())

    def cleanup_room(self, room_name: str) -> None:
        """房间销毁时清理数据"""
        self._ready.pop(room_name, None)
