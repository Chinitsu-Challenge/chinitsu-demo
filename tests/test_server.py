"""
Integration tests for the Chinitsu WebSocket server.

All tests drive the server exclusively through the WebSocket protocol,
so they remain valid after the in-game state store is migrated to Redis
or any other backend — no internal classes are imported or mocked.
"""
import uuid
import pytest
from contextlib import contextmanager
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server import app

# Debug codes from debug_setting.py.
# 114514 → oya hand 11123455678999s: already a complete hand, wins by tsumo immediately.
_DEBUG_TSUMO = 114514


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@contextmanager
def _room(client: TestClient):
    """
    Connect two players to a fresh room and yield (ws1, ws2, room_name).
    The join/host broadcast messages are consumed before yielding so tests
    start with clean queues.
    """
    room = _uid()
    p1, p2 = "p1_" + _uid(), "p2_" + _uid()
    with client.websocket_connect(f"/ws/{room}/{p1}") as ws1:
        ws1.receive_json()  # "Game started… Host is p1"
        with client.websocket_connect(f"/ws/{room}/{p2}") as ws2:
            ws1.receive_json()  # "{p2} joins… Game START!"
            ws2.receive_json()  # same broadcast to p2
            yield ws1, ws2, room


def _start(ws1, ws2, debug_code: int = None):
    """
    Send the 'start' action from ws1, drain both response messages, and
    return (ws_oya, ws_ko) identified by the is_oya flag.
    """
    code = str(debug_code) if debug_code else ""
    ws1.send_json({"action": "start", "card_idx": code})
    msg1 = ws1.receive_json()
    ws2.receive_json()
    return (ws1, ws2) if msg1["is_oya"] else (ws2, ws1)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

class TestConnection:
    def test_first_player_receives_host_broadcast(self, client):
        room = _uid()
        with client.websocket_connect(f"/ws/{room}/alice") as ws:
            msg = ws.receive_json()
        assert msg["broadcast"] is True
        assert "alice" in msg["message"]

    def test_second_player_triggers_game_start_broadcast(self, client):
        room = _uid()
        with client.websocket_connect(f"/ws/{room}/alice") as ws1:
            ws1.receive_json()
            with client.websocket_connect(f"/ws/{room}/bob") as ws2:
                msg1 = ws1.receive_json()
                msg2 = ws2.receive_json()
        assert "Game START" in msg1["message"]
        assert msg1["message"] == msg2["message"]  # same text to both

    def test_third_player_rejected_room_full(self, client):
        room = _uid()
        with client.websocket_connect(f"/ws/{room}/alice") as ws1:
            ws1.receive_json()
            with client.websocket_connect(f"/ws/{room}/bob") as ws2:
                ws1.receive_json()
                ws2.receive_json()
                with client.websocket_connect(f"/ws/{room}/charlie") as ws3:
                    with pytest.raises(WebSocketDisconnect) as exc:
                        ws3.receive_json()
                    assert exc.value.code == 1003

    def test_duplicate_player_id_rejected(self, client):
        room = _uid()
        with client.websocket_connect(f"/ws/{room}/alice") as ws1:
            ws1.receive_json()
            with client.websocket_connect(f"/ws/{room}/alice") as ws2:
                with pytest.raises(WebSocketDisconnect) as exc:
                    ws2.receive_json()
                assert exc.value.code == 1003


# ---------------------------------------------------------------------------
# Game start
# ---------------------------------------------------------------------------

class TestGameStart:
    def test_start_deals_14_to_oya_13_to_ko(self, client):
        with _room(client) as (ws1, ws2, _):
            ws1.send_json({"action": "start", "card_idx": ""})
            msg1 = ws1.receive_json()
            msg2 = ws2.receive_json()
        assert sorted([len(msg1["hand"]), len(msg2["hand"])]) == [13, 14]

    def test_start_assigns_exactly_one_oya(self, client):
        with _room(client) as (ws1, ws2, _):
            ws1.send_json({"action": "start", "card_idx": ""})
            msg1 = ws1.receive_json()
            msg2 = ws2.receive_json()
        assert msg1["is_oya"] != msg2["is_oya"]

    def test_start_deals_only_souzu_tiles(self, client):
        """Chinitsu variant uses only the souzu (bamboo) suit."""
        with _room(client) as (ws1, ws2, _):
            ws1.send_json({"action": "start", "card_idx": ""})
            msg1 = ws1.receive_json()
            msg2 = ws2.receive_json()
        for tile in msg1["hand"] + msg2["hand"]:
            assert tile.endswith("s"), f"unexpected tile suit: {tile}"


# ---------------------------------------------------------------------------
# Turn enforcement
# ---------------------------------------------------------------------------

class TestTurnEnforcement:
    def test_ko_cannot_act_on_oya_turn(self, client):
        with _room(client) as (ws1, ws2, _):
            ws_oya, ws_ko = _start(ws1, ws2)
            ws_ko.send_json({"action": "discard", "card_idx": "0"})
            reply = ws_ko.receive_json()
        assert reply["message"] == "not_your_turn"

    def test_oya_cannot_draw_when_already_after_draw(self, client):
        """Oya starts in after_draw state; drawing again is illegal."""
        with _room(client) as (ws1, ws2, _):
            ws_oya, ws_ko = _start(ws1, ws2)
            ws_oya.send_json({"action": "draw", "card_idx": ""})
            reply = ws_oya.receive_json()
        assert reply["message"] == "illegal_draw"

    def test_oya_cannot_ron_on_own_turn(self, client):
        """Ron is only valid after the opponent discards."""
        with _room(client) as (ws1, ws2, _):
            ws_oya, ws_ko = _start(ws1, ws2)
            ws_oya.send_json({"action": "ron", "card_idx": ""})
            reply = ws_oya.receive_json()
        assert reply["message"] == "not_opponent_turn"


# ---------------------------------------------------------------------------
# Gameplay
# ---------------------------------------------------------------------------

class TestGameplay:
    def test_discard_broadcasts_action_to_both_players(self, client):
        with _room(client) as (ws1, ws2, _):
            ws_oya, ws_ko = _start(ws1, ws2)
            ws_oya.send_json({"action": "discard", "card_idx": "0"})
            oya_reply = ws_oya.receive_json()
            ko_reply = ws_ko.receive_json()
        assert oya_reply["action"] == "discard"
        assert ko_reply["action"] == "discard"
        # kawa should record the discarded tile for oya
        oya_id = oya_reply["player_id"]
        assert len(oya_reply["kawa"][oya_id]) == 1

    def test_draw_discard_cycle_gives_ko_14_tiles(self, client):
        """oya discards → ko skips ron → ko draws → ko has 14 tiles."""
        with _room(client) as (ws1, ws2, _):
            ws_oya, ws_ko = _start(ws1, ws2)

            ws_oya.send_json({"action": "discard", "card_idx": "0"})
            ws_oya.receive_json()
            ws_ko.receive_json()

            ws_ko.send_json({"action": "skip_ron", "card_idx": ""})
            ws_oya.receive_json()
            ws_ko.receive_json()

            ws_ko.send_json({"action": "draw", "card_idx": ""})
            ko_draw = ws_ko.receive_json()
            ws_oya.receive_json()

        assert ko_draw["action"] == "draw"
        assert len(ko_draw["hand"]) == 14

    def test_tsumo_win_with_debug_hand(self, client):
        """
        Debug code 114514 gives oya the complete hand 11123455678999s.
        Oya can declare tsumo on the very first action.
        """
        with _room(client) as (ws1, ws2, _):
            ws_oya, ws_ko = _start(ws1, ws2, debug_code=_DEBUG_TSUMO)
            ws_oya.send_json({"action": "tsumo", "card_idx": ""})
            oya_result = ws_oya.receive_json()
            ko_result = ws_ko.receive_json()

        assert oya_result["agari"] is True
        assert oya_result["han"] > 0
        # both players receive the same winner id in the public result
        assert ko_result["agari"] is True
        assert ko_result["player_id"] == oya_result["player_id"]

    def test_riichi_flags_kawa_entry(self, client):
        """Riichi declaration marks the discarded tile in the kawa."""
        with _room(client) as (ws1, ws2, _):
            ws_oya, ws_ko = _start(ws1, ws2)
            ws_oya.send_json({"action": "riichi", "card_idx": "0"})
            oya_reply = ws_oya.receive_json()
            ws_ko.receive_json()

        assert oya_reply["action"] == "riichi"
        oya_id = oya_reply["player_id"]
        last_kawa_entry = oya_reply["kawa"][oya_id][-1]
        assert last_kawa_entry[1] is True  # (tile, is_riichi=True)
