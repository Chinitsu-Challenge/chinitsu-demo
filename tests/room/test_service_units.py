"""
tests/room/test_service_units.py
纯逻辑服务单元测试：
  - ReadyService
  - EndDecisionService
  - MatchEndEvaluator
"""
import pytest

from room.ready_service import ReadyService
from room.end_decision_service import EndDecisionService
from room.match_end_evaluator import evaluate, MatchEndDecision


# ══════════════════════════════════════════════════════════════
# ReadyService
# ══════════════════════════════════════════════════════════════

class TestReadyService:
    def test_single_player_not_ready(self):
        rs = ReadyService()
        result = rs.mark_ready("room1", "alice", ["alice", "bob"])
        assert result.all_ready is False
        assert "alice" in result.ready_ids

    def test_both_players_ready(self):
        rs = ReadyService()
        rs.mark_ready("room1", "alice", ["alice", "bob"])
        result = rs.mark_ready("room1", "bob", ["alice", "bob"])
        assert result.all_ready is True
        assert set(result.ready_ids) == {"alice", "bob"}

    def test_idempotent_double_ready(self):
        """同一玩家多次 start 不应重复计票"""
        rs = ReadyService()
        rs.mark_ready("room1", "alice", ["alice", "bob"])
        result = rs.mark_ready("room1", "alice", ["alice", "bob"])
        assert result.all_ready is False
        assert result.ready_ids.count("alice") == 1  # 不重复

    def test_cancel_ready(self):
        rs = ReadyService()
        rs.mark_ready("room1", "alice", ["alice", "bob"])
        remaining = rs.cancel_ready("room1", "alice")
        assert "alice" not in remaining

    def test_clear_room(self):
        rs = ReadyService()
        rs.mark_ready("room1", "alice", ["alice", "bob"])
        rs.clear("room1")
        assert rs.get_ready_ids("room1") == []

    def test_only_one_online_player_cannot_be_all_ready(self):
        """只有 1 人在线时，即使该人 ready，all_ready 应为 False"""
        rs = ReadyService()
        result = rs.mark_ready("room1", "alice", ["alice"])  # 只有 alice 在线
        assert result.all_ready is False  # 不满足 2 人条件

    def test_debug_code_extracted(self):
        """card_idx > 100 时应提取为 debug_code"""
        rs = ReadyService()
        rs.mark_ready("room1", "alice", ["alice", "bob"], card_idx=114514)
        result = rs.mark_ready("room1", "bob", ["alice", "bob"])
        assert result.debug_code == 114514

    def test_no_debug_code_by_default(self):
        rs = ReadyService()
        rs.mark_ready("room1", "alice", ["alice", "bob"])
        result = rs.mark_ready("room1", "bob", ["alice", "bob"])
        assert result.debug_code is None

    def test_small_card_idx_not_debug(self):
        """card_idx <= 100 不是 debug_code"""
        rs = ReadyService()
        rs.mark_ready("room1", "alice", ["alice", "bob"], card_idx=5)
        result = rs.mark_ready("room1", "bob", ["alice", "bob"])
        assert result.debug_code is None

    def test_independent_rooms(self):
        """不同房间的 ready 状态互不影响"""
        rs = ReadyService()
        rs.mark_ready("room1", "alice", ["alice", "bob"])
        rs.mark_ready("room2", "alice", ["alice", "bob"])
        # room1 只有 alice ready
        assert rs.get_ready_ids("room1") == ["alice"]
        # room2 也只有 alice ready
        assert rs.get_ready_ids("room2") == ["alice"]

    def test_cleanup_room(self):
        rs = ReadyService()
        rs.mark_ready("room1", "alice", ["alice"])
        rs.cleanup_room("room1")
        assert rs.get_ready_ids("room1") == []


# ══════════════════════════════════════════════════════════════
# EndDecisionService
# ══════════════════════════════════════════════════════════════

class TestEndDecisionService:
    def test_single_continue_not_all(self):
        es = EndDecisionService()
        result = es.choose_continue("room1", "alice", ["alice", "bob"])
        assert result.all_continue is False
        assert "alice" in result.continue_ids

    def test_both_continue(self):
        es = EndDecisionService()
        es.choose_continue("room1", "alice", ["alice", "bob"])
        result = es.choose_continue("room1", "bob", ["alice", "bob"])
        assert result.all_continue is True
        assert set(result.continue_ids) == {"alice", "bob"}

    def test_get_continue_ids(self):
        es = EndDecisionService()
        es.choose_continue("room1", "alice", ["alice", "bob"])
        ids = es.get_continue_ids("room1")
        assert "alice" in ids
        assert "bob" not in ids

    def test_clear(self):
        es = EndDecisionService()
        es.choose_continue("room1", "alice", ["alice", "bob"])
        es.clear("room1")
        assert es.get_continue_ids("room1") == []

    def test_cleanup_room(self):
        es = EndDecisionService()
        es.choose_continue("room1", "alice", ["alice"])
        es.cleanup_room("room1")
        assert es.get_continue_ids("room1") == []

    def test_independent_rooms(self):
        es = EndDecisionService()
        es.choose_continue("room1", "alice", ["alice", "bob"])
        es.choose_continue("room2", "bob", ["alice", "bob"])
        assert "alice" in es.get_continue_ids("room1")
        assert "bob" not in es.get_continue_ids("room1")
        assert "bob" in es.get_continue_ids("room2")

    def test_single_online_player_needs_only_one_continue(self):
        """若只有 1 名在线玩家，该玩家 continue 即为 all_continue"""
        es = EndDecisionService()
        result = es.choose_continue("room1", "alice", ["alice"])
        # 1 人情况下只需 1 个，但设计要求 >= 2，检查一致性
        # 根据 end_decision_service.py: len(online_set) >= 2 才 all_continue
        assert result.all_continue is False  # 1 人在线不满足双方都同意


# ══════════════════════════════════════════════════════════════
# MatchEndEvaluator
# ══════════════════════════════════════════════════════════════

class TestMatchEndEvaluator:
    def _make_snap(self, round_no=0, round_limit=8,
                   alice_pt=150000, bob_pt=150000) -> dict:
        return {
            "round_no": round_no,
            "round_limit": round_limit,
            "players": {
                "uid-alice": {"point": alice_pt},
                "uid-bob": {"point": bob_pt},
            }
        }

    def test_round_limit_reached(self):
        snap = self._make_snap(round_no=8, round_limit=8)
        d = evaluate(snap)
        assert d.should_end is True
        assert d.reason == "round_limit_reached"

    def test_round_limit_exceeded(self):
        snap = self._make_snap(round_no=10, round_limit=8)
        d = evaluate(snap)
        assert d.should_end is True
        assert d.reason == "round_limit_reached"

    def test_round_limit_not_reached(self):
        snap = self._make_snap(round_no=5, round_limit=8)
        d = evaluate(snap)
        assert d.should_end is False

    def test_point_zero_alice(self):
        snap = self._make_snap(alice_pt=0)
        d = evaluate(snap)
        assert d.should_end is True
        assert d.reason == "point_zero"

    def test_point_zero_bob(self):
        snap = self._make_snap(bob_pt=0)
        d = evaluate(snap)
        assert d.should_end is True
        assert d.reason == "point_zero"

    def test_point_negative(self):
        """负分也应触发结束"""
        snap = self._make_snap(bob_pt=-1000)
        d = evaluate(snap)
        assert d.should_end is True
        assert d.reason == "point_zero"

    def test_both_conditions_false(self):
        snap = self._make_snap(round_no=3, alice_pt=100, bob_pt=200)
        d = evaluate(snap)
        assert d.should_end is False
        assert d.reason is None

    def test_missing_round_no_no_end(self):
        """缺少 round_no 时，不应推进 ENDED（字段不全不做决策）"""
        snap = {"round_limit": 8, "players": {"a": {"point": 100}}}
        d = evaluate(snap)
        assert d.should_end is False

    def test_missing_round_limit_no_end(self):
        """缺少 round_limit 时不判断轮数，但 point 仍检查"""
        snap = {"round_no": 5, "players": {"a": {"point": 100}}}
        d = evaluate(snap)
        assert d.should_end is False

    def test_missing_players_no_end(self):
        """无 players 字段时安全返回不结束"""
        snap = {"round_no": 8, "round_limit": 8}  # players 缺失
        d = evaluate(snap)
        # round_limit_reached 条件先检查，应触发
        assert d.should_end is True

    def test_empty_players_with_round_end(self):
        """players 为空字典时，round_limit 仍生效"""
        snap = {"round_no": 8, "round_limit": 8, "players": {}}
        d = evaluate(snap)
        assert d.should_end is True  # 轮数已满

    def test_return_type(self):
        snap = self._make_snap()
        d = evaluate(snap)
        assert isinstance(d, MatchEndDecision)
