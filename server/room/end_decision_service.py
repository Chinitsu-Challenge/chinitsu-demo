# room/end_decision_service.py — ENDED 阶段继续/结束决策服务
# 管理 ENDED 状态下的 continue_game / end_game 决策流程。
# 任一方 end_game → 立即销毁；双方都 continue_game → 回到 WAITING。

import logging

logger = logging.getLogger("uvicorn")


class ContinueResult:
    """choose_continue 的返回结果"""
    def __init__(self, all_continue: bool, continue_ids: list[str]):
        self.all_continue = all_continue   # 是否双方都选择了继续
        self.continue_ids = continue_ids   # 当前已选择继续的玩家列表


class EndDecisionService:
    """
    ENDED 阶段的决策管理。
    - continue_game：标记玩家愿意继续
    - end_game：任意一方即可结束（由调用方触发 ANY_END_GAME）
    - 双方都 continue → 返回 all_continue=True
    """

    def __init__(self):
        # room_name -> set of user_ids that chose continue
        self._continue: dict[str, set[str]] = {}

    def choose_continue(
        self,
        room_name: str,
        user_id: str,
        online_user_ids: list[str],
    ) -> ContinueResult:
        """
        标记玩家选择继续。
        online_user_ids: 当前房间在线玩家列表。
        返回 ContinueResult，由调用方决定是否触发 BOTH_CONTINUE。
        """
        if room_name not in self._continue:
            self._continue[room_name] = set()

        self._continue[room_name].add(user_id)

        continue_set = self._continue[room_name]
        online_set = set(online_user_ids)
        all_continue = len(online_set) >= 2 and online_set.issubset(continue_set)

        return ContinueResult(
            all_continue=all_continue,
            continue_ids=list(continue_set & online_set),
        )

    def get_continue_ids(self, room_name: str) -> list[str]:
        """获取当前已选择继续的玩家列表"""
        return list(self._continue.get(room_name, set()))

    def clear(self, room_name: str) -> None:
        """清空房间的继续投票（状态切换/玩家变动时调用）"""
        self._continue.pop(room_name, None)

    def cleanup_room(self, room_name: str) -> None:
        """房间销毁时清理"""
        self._continue.pop(room_name, None)
