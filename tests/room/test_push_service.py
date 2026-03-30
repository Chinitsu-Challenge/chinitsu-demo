"""
tests/room/test_push_service.py
PushService 单元测试：单播、广播、连接关闭。
"""
import pytest
from tests.room.conftest import MockWebSocket, run_async

from room.models import PlayerSession
from room.push_service import PushService


def make_sessions(user_ids: list[str], online_flags: list[bool] = None) -> dict:
    """构建 sessions_store 字典（room_name -> {user_id -> session}）"""
    online_flags = online_flags or [True] * len(user_ids)
    room_sessions = {}
    for uid, online in zip(user_ids, online_flags):
        ws = MockWebSocket(uid) if online else None
        session = PlayerSession(
            user_id=uid, display_name=uid.title(),
            room_name="testroom", seat=len(room_sessions),
            is_owner=(len(room_sessions) == 0),
            online=online, ws=ws
        )
        room_sessions[uid] = session
    return {"testroom": room_sessions}


class TestUnicast:
    def test_unicast_online_player(self):
        async def inner():
            store = make_sessions(["alice", "bob"])
            svc = PushService(store)
            payload = {"event": "test", "broadcast": False}
            result = await svc.unicast("testroom", "alice", payload)
            assert result is True
            assert store["testroom"]["alice"].ws.sent == [payload]

        run_async(inner())

    def test_unicast_offline_player_returns_false(self):
        async def inner():
            store = make_sessions(["alice", "bob"], online_flags=[False, True])
            svc = PushService(store)
            result = await svc.unicast("testroom", "alice", {"event": "x"})
            assert result is False

        run_async(inner())

    def test_unicast_nonexistent_user_returns_false(self):
        async def inner():
            store = make_sessions(["alice"])
            svc = PushService(store)
            result = await svc.unicast("testroom", "nonexistent", {"event": "x"})
            assert result is False

        run_async(inner())

    def test_unicast_nonexistent_room_returns_false(self):
        async def inner():
            store = {}
            svc = PushService(store)
            result = await svc.unicast("no-room", "alice", {"event": "x"})
            assert result is False

        run_async(inner())

    def test_unicast_preserves_payload(self):
        """消息内容应完整保留"""
        async def inner():
            store = make_sessions(["alice"])
            svc = PushService(store)
            payload = {"event": "game_started", "hand": ["1s", "2s"], "broadcast": False}
            await svc.unicast("testroom", "alice", payload)
            received = store["testroom"]["alice"].ws.sent[0]
            assert received["hand"] == ["1s", "2s"]

        run_async(inner())


class TestBroadcast:
    def test_broadcast_sends_to_all_online(self):
        async def inner():
            store = make_sessions(["alice", "bob"])
            svc = PushService(store)
            payload = {"event": "opponent_disconnected", "broadcast": True}
            sent_count = await svc.broadcast("testroom", payload)
            assert sent_count == 2
            assert store["testroom"]["alice"].ws.sent == [payload]
            assert store["testroom"]["bob"].ws.sent == [payload]

        run_async(inner())

    def test_broadcast_skips_offline_players(self):
        async def inner():
            store = make_sessions(["alice", "bob"], online_flags=[True, False])
            svc = PushService(store)
            count = await svc.broadcast("testroom", {"event": "x"})
            assert count == 1  # 只有 alice 在线

        run_async(inner())

    def test_broadcast_with_exclude(self):
        async def inner():
            store = make_sessions(["alice", "bob"])
            svc = PushService(store)
            await svc.broadcast("testroom", {"event": "x"}, exclude="alice")
            # alice 不应收到
            assert store["testroom"]["alice"].ws.sent == []
            assert len(store["testroom"]["bob"].ws.sent) == 1

        run_async(inner())

    def test_broadcast_empty_room(self):
        async def inner():
            store = {"testroom": {}}
            svc = PushService(store)
            count = await svc.broadcast("testroom", {"event": "x"})
            assert count == 0

        run_async(inner())

    def test_broadcast_nonexistent_room(self):
        async def inner():
            store = {}
            svc = PushService(store)
            count = await svc.broadcast("no-room", {"event": "x"})
            assert count == 0

        run_async(inner())


class TestGetHelpers:
    def test_get_online_user_ids(self):
        store = make_sessions(["alice", "bob"], online_flags=[True, False])
        svc = PushService(store)
        online = svc.get_online_user_ids("testroom")
        assert "alice" in online
        assert "bob" not in online

    def test_get_online_all_offline(self):
        store = make_sessions(["alice"], online_flags=[False])
        svc = PushService(store)
        assert svc.get_online_user_ids("testroom") == []

    def test_get_opponent_id(self):
        store = make_sessions(["alice", "bob"])
        svc = PushService(store)
        assert svc.get_opponent_id("testroom", "alice") == "bob"
        assert svc.get_opponent_id("testroom", "bob") == "alice"

    def test_get_opponent_id_single_player(self):
        store = make_sessions(["alice"])
        svc = PushService(store)
        assert svc.get_opponent_id("testroom", "alice") is None


class TestCloseAllConnections:
    def test_close_all_marks_ws_none(self):
        async def inner():
            store = make_sessions(["alice", "bob"])
            alice_ws = store["testroom"]["alice"].ws
            bob_ws = store["testroom"]["bob"].ws
            svc = PushService(store)
            await svc.close_all_connections("testroom", code=1001, reason="room_expired")
            assert alice_ws.closed is True
            assert alice_ws.close_code == 1001
            assert alice_ws.close_reason == "room_expired"
            assert bob_ws.closed is True
            # session.ws 应被置为 None
            assert store["testroom"]["alice"].ws is None

        run_async(inner())
