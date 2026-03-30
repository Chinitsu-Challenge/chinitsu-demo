"""
tests/room/test_models.py
Room 与 PlayerSession 数据类单元测试：序列化、状态变更等。
"""
import time
import pytest
from tests.room.conftest import MockWebSocket

from room.models import Room, PlayerSession, RoomStatus, ROOM_MAX_LIFETIME_SEC, DEFAULT_ROUND_LIMIT


class TestRoom:
    def test_default_creation(self):
        room = Room(room_id="rid-1", room_name="hall")
        assert room.status == RoomStatus.WAITING
        assert room.player_ids == []
        assert room.ready_user_ids == set()
        assert room.continue_user_ids == set()
        assert room.round_no == 0
        assert room.round_limit == DEFAULT_ROUND_LIMIT

    def test_expires_at_set_on_creation(self):
        before = time.time()
        room = Room(room_id="rid", room_name="r")
        after = time.time()
        assert before + ROOM_MAX_LIFETIME_SEC <= room.expires_at <= after + ROOM_MAX_LIFETIME_SEC

    def test_is_full_false_with_one_player(self):
        room = Room(room_id="r", room_name="r", player_ids=["a"])
        assert not room.is_full

    def test_is_full_true_with_two_players(self):
        room = Room(room_id="r", room_name="r", player_ids=["a", "b"])
        assert room.is_full

    def test_touch_updates_updated_at(self):
        room = Room(room_id="r", room_name="r")
        old_ts = room.updated_at
        time.sleep(0.01)
        room.touch()
        assert room.updated_at > old_ts

    def test_to_redis_dict_contains_required_keys(self):
        room = Room(room_id="rid", room_name="hall", owner_id="alice",
                    player_ids=["alice", "bob"])
        d = room.to_redis_dict()
        for key in ("room_id", "room_name", "status", "owner_id", "player_ids",
                    "created_at", "expires_at", "ready_user_ids", "round_no", "round_limit"):
            assert key in d, f"Missing key: {key}"

    def test_to_redis_dict_serializes_sets_as_json(self):
        import json
        room = Room(room_id="r", room_name="r", ready_user_ids={"alice"})
        d = room.to_redis_dict()
        ready_list = json.loads(d["ready_user_ids"])
        assert "alice" in ready_list

    def test_roundtrip_serialization(self):
        room = Room(
            room_id="rid-123",
            room_name="myroom",
            status=RoomStatus.RUNNING,
            owner_id="uid-alice",
            player_ids=["uid-alice", "uid-bob"],
            round_no=3,
            round_limit=8,
            ready_user_ids={"uid-alice"},
            continue_user_ids={"uid-bob"},
        )
        restored = Room.from_redis_dict(room.to_redis_dict())
        assert restored.room_id == room.room_id
        assert restored.room_name == room.room_name
        assert restored.status == room.status
        assert restored.owner_id == room.owner_id
        assert restored.player_ids == room.player_ids
        assert restored.round_no == room.round_no
        assert restored.round_limit == room.round_limit
        assert "uid-alice" in restored.ready_user_ids
        assert "uid-bob" in restored.continue_user_ids

    def test_from_redis_dict_defaults(self):
        """缺少部分字段时应使用默认值，不抛异常"""
        minimal = {
            "room_id": "rid",
            "room_name": "r",
            "status": "waiting",
            "owner_id": "alice",
            "player_ids": "[]",
            "created_at": str(time.time()),
            "updated_at": str(time.time()),
            "expires_at": str(time.time() + 2400),
            "ready_user_ids": "[]",
            "continue_user_ids": "[]",
        }
        room = Room.from_redis_dict(minimal)
        assert room.round_no == 0
        assert room.round_limit == DEFAULT_ROUND_LIMIT


class TestPlayerSession:
    def test_default_creation(self):
        ws = MockWebSocket("alice")
        session = PlayerSession(
            user_id="uid-alice",
            display_name="Alice",
            room_name="hall",
            seat=0,
            is_owner=True,
            ws=ws,
        )
        assert session.online is True
        assert session.last_seen is None
        assert session.connection_id is not None

    def test_mark_offline(self):
        ws = MockWebSocket("alice")
        session = PlayerSession(
            user_id="uid-alice", display_name="Alice",
            room_name="hall", seat=0, is_owner=True, ws=ws
        )
        before = time.time()
        session.mark_offline()
        assert session.online is False
        assert session.ws is None
        assert session.last_seen is not None
        assert session.last_seen >= before

    def test_mark_online(self):
        ws_old = MockWebSocket("alice")
        session = PlayerSession(
            user_id="uid-alice", display_name="Alice",
            room_name="hall", seat=0, is_owner=True, ws=ws_old
        )
        session.mark_offline()
        old_conn_id = session.connection_id

        ws_new = MockWebSocket("alice-new")
        session.mark_online(ws_new, "new-conn-id")

        assert session.online is True
        assert session.ws is ws_new
        assert session.last_seen is None
        assert session.connection_id == "new-conn-id"

    def test_mark_online_generates_connection_id_if_not_provided(self):
        session = PlayerSession(
            user_id="uid-alice", display_name="Alice",
            room_name="hall", seat=0, is_owner=True
        )
        session.mark_offline()
        ws = MockWebSocket()
        session.mark_online(ws)
        assert session.connection_id is not None
        assert len(session.connection_id) > 0

    def test_to_redis_dict(self):
        ws = MockWebSocket("alice")
        session = PlayerSession(
            user_id="uid-alice", display_name="Alice",
            room_name="hall", seat=1, is_owner=False, ws=ws,
            connection_id="conn-123"
        )
        d = session.to_redis_dict()
        assert d["user_id"] == "uid-alice"
        assert d["display_name"] == "Alice"
        assert d["room_name"] == "hall"
        assert d["seat"] == "1"
        assert d["is_owner"] == "false"
        assert d["online"] == "true"
        assert d["connection_id"] == "conn-123"
        # ws 不应被序列化
        assert "ws" not in d

    def test_to_redis_dict_offline(self):
        session = PlayerSession(
            user_id="uid-bob", display_name="Bob",
            room_name="hall", seat=0, is_owner=True
        )
        session.mark_offline()
        d = session.to_redis_dict()
        assert d["online"] == "false"
        assert float(d["last_seen"]) > 0
