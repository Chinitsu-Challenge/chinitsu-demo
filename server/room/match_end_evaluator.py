# room/match_end_evaluator.py — 比赛结束条件评估器
# 纯函数，根据权威快照判断整个比赛（多轮）是否应该结束。
# 不执行任何游戏逻辑，不修改状态，只做只读判断。

import logging

logger = logging.getLogger("uvicorn")


class MatchEndDecision:
    """评估结果"""
    def __init__(self, should_end: bool, reason: str | None = None):
        self.should_end = should_end    # 是否应该结束比赛
        self.reason = reason             # 结束原因（round_limit_reached / point_zero / None）


def evaluate(snapshot: dict) -> MatchEndDecision:
    """
    根据快照判断比赛是否应该结束。

    结束条件（满足任一即结束）：
    1. round_no >= round_limit（已打完所有轮次）
    2. 任一方 point < 0（点数归零）

    若快照缺少关键字段，返回 should_end=False（不能在信息不全时做决策）。
    """
    round_no = snapshot.get("round_no")
    round_limit = snapshot.get("round_limit")
    players = snapshot.get("players", {})

    # 检查轮数上限
    if round_no is not None and round_limit is not None:
        if round_no >= round_limit:
            logger.info("比赛结束：轮数达到上限 (%d/%d)", round_no, round_limit)
            return MatchEndDecision(should_end=True, reason="round_limit_reached")

    # 检查点数归零
    for pid, pdata in players.items():
        point = pdata.get("point")
        if point is not None and point < 0:
            logger.info("比赛结束：玩家 %s 点数归零 (%d)", pid, point)
            return MatchEndDecision(should_end=True, reason="point_zero")

    return MatchEndDecision(should_end=False, reason=None)
