"""
tests/room/test_protocol.py
协议消息构造函数单元测试：验证所有 payload 格式正确。
"""
import pytest

from room import protocol


class TestProtocolFormat:
    """所有 payload 都必须包含 broadcast 和 event 字段"""

    def _check_base(self, msg: dict, *, broadcast: bool, event: str):
        assert "broadcast" in msg, f"Missing 'broadcast' in {msg}"
        assert "event" in msg, f"Missing 'event' in {msg}"
        assert msg["broadcast"] == broadcast
        assert msg["event"] == event

    # ── 错误消息 ──────────────────────────────────────────────

    def test_make_error_structure(self):
        msg = protocol.make_error("game_paused", "Game is paused")
        self._check_base(msg, broadcast=False, event="error")
        assert msg["code"] == "game_paused"
        assert msg["message"] == "Game is paused"

    def test_make_error_default_message(self):
        msg = protocol.make_error("game_paused")
        assert msg["message"] == "game_paused"  # 默认使用 code 作为 message

    # ── 房间类事件 ────────────────────────────────────────────

    def test_make_player_joined(self):
        msg = protocol.make_player_joined("Bob", "testroom", 2)
        self._check_base(msg, broadcast=True, event="player_joined")
        assert msg["display_name"] == "Bob"
        assert msg["room_name"] == "testroom"
        assert msg["player_count"] == 2

    def test_make_player_left(self):
        msg = protocol.make_player_left("Alice", "testroom", 1)
        self._check_base(msg, broadcast=True, event="player_left")
        assert msg["display_name"] == "Alice"
        assert msg["player_count"] == 1

    def test_make_start_ready_changed_not_all(self):
        msg = protocol.make_start_ready_changed(["uid-alice"], False)
        self._check_base(msg, broadcast=True, event="start_ready_changed")
        assert msg["all_ready"] is False
        assert "uid-alice" in msg["ready_user_ids"]

    def test_make_start_ready_changed_all(self):
        msg = protocol.make_start_ready_changed(["a", "b"], True)
        assert msg["all_ready"] is True

    def test_make_continue_vote_changed(self):
        msg = protocol.make_continue_vote_changed(["uid-bob"], False)
        self._check_base(msg, broadcast=True, event="continue_vote_changed")
        assert "uid-bob" in msg["continue_user_ids"]
        assert msg["all_continue"] is False

    def test_make_room_expired(self):
        msg = protocol.make_room_expired("hall")
        self._check_base(msg, broadcast=True, event="room_expired")
        assert msg["room_name"] == "hall"

    def test_make_room_closed(self):
        msg = protocol.make_room_closed("player_end_game")
        self._check_base(msg, broadcast=True, event="room_closed")
        assert msg["reason"] == "player_end_game"

    def test_make_match_ended(self):
        scores = {"uid-alice": 200, "uid-bob": 100}
        msg = protocol.make_match_ended("point_zero", scores, winner_id="uid-alice")
        self._check_base(msg, broadcast=True, event="match_ended")
        assert msg["reason"] == "point_zero"
        assert msg["final_scores"]["uid-alice"] == 200
        assert msg["winner_id"] == "uid-alice"

    def test_make_match_ended_draw(self):
        scores = {"uid-alice": 150, "uid-bob": 150}
        msg = protocol.make_match_ended("round_limit_reached", scores, winner_id=None)
        assert msg["winner_id"] is None

    # ── 重连类事件 ────────────────────────────────────────────

    def test_make_opponent_disconnected(self):
        msg = protocol.make_opponent_disconnected()
        self._check_base(msg, broadcast=False, event="opponent_disconnected")

    def test_make_opponent_reconnected(self):
        msg = protocol.make_opponent_reconnected()
        self._check_base(msg, broadcast=False, event="opponent_reconnected")

    def test_make_reconnect_timeout(self):
        msg = protocol.make_reconnect_timeout("uid-alice", "uid-bob")
        self._check_base(msg, broadcast=True, event="reconnect_timeout")
        assert msg["winner_id"] == "uid-alice"
        assert msg["loser_id"] == "uid-bob"

    # ── 超时类事件 ────────────────────────────────────────────

    def test_make_timeout_warning(self):
        msg = protocol.make_timeout_warning(30)
        self._check_base(msg, broadcast=False, event="timeout_warning")
        assert msg["seconds_left"] == 30

    def test_make_auto_action(self):
        msg = protocol.make_auto_action("skip_ron")
        self._check_base(msg, broadcast=False, event="auto_action")
        assert msg["action"] == "skip_ron"
