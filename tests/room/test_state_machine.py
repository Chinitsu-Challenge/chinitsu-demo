"""
tests/room/test_state_machine.py
房间状态机单元测试：覆盖所有合法与非法转移路径。
"""
import pytest
from tests.room.conftest import *  # noqa: F401, F403

from room.models import RoomStatus, RoomEvent
from room.state_machine import transition, can_transition
from room.errors import InvalidTransitionError


# ══════════════════════════════════════════════════════════════
# 合法转移：WAITING
# ══════════════════════════════════════════════════════════════

class TestWaitingTransitions:
    def test_waiting_both_ready_to_running(self):
        assert transition(RoomStatus.WAITING, RoomEvent.BOTH_READY) == RoomStatus.RUNNING

    def test_waiting_all_left_to_destroyed(self):
        assert transition(RoomStatus.WAITING, RoomEvent.ALL_LEFT) == RoomStatus.DESTROYED

    def test_waiting_room_expired_to_destroyed(self):
        assert transition(RoomStatus.WAITING, RoomEvent.ROOM_EXPIRED) == RoomStatus.DESTROYED

    def test_waiting_invalid_match_end(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.WAITING, RoomEvent.MATCH_END)

    def test_waiting_invalid_player_disconnect(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.WAITING, RoomEvent.PLAYER_DISCONNECT)

    def test_waiting_invalid_player_reconnect(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.WAITING, RoomEvent.PLAYER_RECONNECT)

    def test_waiting_invalid_both_continue(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.WAITING, RoomEvent.BOTH_CONTINUE)

    def test_waiting_invalid_any_end_game(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.WAITING, RoomEvent.ANY_END_GAME)

    def test_waiting_invalid_both_offline(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.WAITING, RoomEvent.BOTH_OFFLINE)


# ══════════════════════════════════════════════════════════════
# 合法转移：RUNNING
# ══════════════════════════════════════════════════════════════

class TestRunningTransitions:
    def test_running_player_disconnect_to_reconnect(self):
        assert transition(RoomStatus.RUNNING, RoomEvent.PLAYER_DISCONNECT) == RoomStatus.RECONNECT

    def test_running_match_end_to_ended(self):
        assert transition(RoomStatus.RUNNING, RoomEvent.MATCH_END) == RoomStatus.ENDED

    def test_running_room_expired_to_destroyed(self):
        assert transition(RoomStatus.RUNNING, RoomEvent.ROOM_EXPIRED) == RoomStatus.DESTROYED

    def test_running_all_left_to_destroyed(self):
        assert transition(RoomStatus.RUNNING, RoomEvent.ALL_LEFT) == RoomStatus.DESTROYED

    def test_running_invalid_both_ready(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.RUNNING, RoomEvent.BOTH_READY)

    def test_running_invalid_player_reconnect(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.RUNNING, RoomEvent.PLAYER_RECONNECT)

    def test_running_invalid_both_continue(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.RUNNING, RoomEvent.BOTH_CONTINUE)

    def test_running_invalid_any_end_game(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.RUNNING, RoomEvent.ANY_END_GAME)

    def test_running_invalid_both_offline(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.RUNNING, RoomEvent.BOTH_OFFLINE)

    def test_running_invalid_reconnect_timeout(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.RUNNING, RoomEvent.RECONNECT_TIMEOUT)


# ══════════════════════════════════════════════════════════════
# 合法转移：RECONNECT
# ══════════════════════════════════════════════════════════════

class TestReconnectTransitions:
    def test_reconnect_player_reconnect_to_running(self):
        assert transition(RoomStatus.RECONNECT, RoomEvent.PLAYER_RECONNECT) == RoomStatus.RUNNING

    def test_reconnect_timeout_to_ended(self):
        assert transition(RoomStatus.RECONNECT, RoomEvent.RECONNECT_TIMEOUT) == RoomStatus.ENDED

    def test_reconnect_both_offline_to_destroyed(self):
        assert transition(RoomStatus.RECONNECT, RoomEvent.BOTH_OFFLINE) == RoomStatus.DESTROYED

    def test_reconnect_room_expired_to_destroyed(self):
        assert transition(RoomStatus.RECONNECT, RoomEvent.ROOM_EXPIRED) == RoomStatus.DESTROYED

    def test_reconnect_all_left_to_destroyed(self):
        assert transition(RoomStatus.RECONNECT, RoomEvent.ALL_LEFT) == RoomStatus.DESTROYED

    def test_reconnect_invalid_match_end(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.RECONNECT, RoomEvent.MATCH_END)

    def test_reconnect_invalid_both_ready(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.RECONNECT, RoomEvent.BOTH_READY)

    def test_reconnect_invalid_both_continue(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.RECONNECT, RoomEvent.BOTH_CONTINUE)


# ══════════════════════════════════════════════════════════════
# 合法转移：ENDED
# ══════════════════════════════════════════════════════════════

class TestEndedTransitions:
    def test_ended_both_continue_to_waiting(self):
        assert transition(RoomStatus.ENDED, RoomEvent.BOTH_CONTINUE) == RoomStatus.WAITING

    def test_ended_any_end_game_to_destroyed(self):
        assert transition(RoomStatus.ENDED, RoomEvent.ANY_END_GAME) == RoomStatus.DESTROYED

    def test_ended_room_expired_to_destroyed(self):
        assert transition(RoomStatus.ENDED, RoomEvent.ROOM_EXPIRED) == RoomStatus.DESTROYED

    def test_ended_all_left_to_destroyed(self):
        assert transition(RoomStatus.ENDED, RoomEvent.ALL_LEFT) == RoomStatus.DESTROYED

    def test_ended_invalid_match_end(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.ENDED, RoomEvent.MATCH_END)

    def test_ended_invalid_player_disconnect(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.ENDED, RoomEvent.PLAYER_DISCONNECT)

    def test_ended_invalid_both_ready(self):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.ENDED, RoomEvent.BOTH_READY)


# ══════════════════════════════════════════════════════════════
# DESTROYED 状态：所有事件都应失败
# ══════════════════════════════════════════════════════════════

class TestDestroyedTransitions:
    @pytest.mark.parametrize("event", list(RoomEvent))
    def test_destroyed_all_events_invalid(self, event):
        with pytest.raises(InvalidTransitionError):
            transition(RoomStatus.DESTROYED, event)


# ══════════════════════════════════════════════════════════════
# can_transition 函数
# ══════════════════════════════════════════════════════════════

class TestCanTransition:
    def test_can_transition_valid(self):
        assert can_transition(RoomStatus.WAITING, RoomEvent.BOTH_READY) is True

    def test_can_transition_invalid(self):
        assert can_transition(RoomStatus.WAITING, RoomEvent.MATCH_END) is False

    def test_can_transition_from_destroyed(self):
        assert can_transition(RoomStatus.DESTROYED, RoomEvent.ROOM_EXPIRED) is False

    def test_all_valid_transitions_consistent(self):
        """can_transition 和 transition 结果必须一致"""
        for status in [s for s in RoomStatus if s != RoomStatus.DESTROYED]:
            for event in RoomEvent:
                if can_transition(status, event):
                    # 合法路径：transition 不应抛异常
                    result = transition(status, event)
                    assert result != status or result == RoomStatus.DESTROYED


# ══════════════════════════════════════════════════════════════
# InvalidTransitionError 结构
# ══════════════════════════════════════════════════════════════

class TestInvalidTransitionError:
    def test_error_has_current_status(self):
        try:
            transition(RoomStatus.WAITING, RoomEvent.MATCH_END)
        except InvalidTransitionError as e:
            assert e.current_status == "waiting"
            assert e.event == "match_end"
            assert "waiting" in str(e)

    def test_error_is_room_error(self):
        from room.errors import RoomError
        try:
            transition(RoomStatus.ENDED, RoomEvent.PLAYER_RECONNECT)
        except InvalidTransitionError as e:
            assert isinstance(e, RoomError)
