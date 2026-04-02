"""
Integration tests for the Chinitsu WebSocket server.

All tests drive the server exclusively through the WebSocket protocol and
HTTP auth endpoints, so they remain valid after the in-game state store is
migrated to Redis or any other backend — no internal classes are imported
or mocked.
"""
import uuid
import pytest
from contextlib import contextmanager
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import app

# Debug codes from debug_setting.py.
# 114514 → oya hand 11123455678999s: already a complete hand, wins by tsumo immediately.
_DEBUG_TSUMO = 114514


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _register(client: TestClient, username: str, password: str = "testpass") -> str:
    resp = client.post("/api/register", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@contextmanager
def _room(client: TestClient):
    """
    Register two players, connect them to a fresh room, and yield
    (ws1, ws2, room_name).  The join/host broadcast messages are consumed
    before yielding so tests start with clean queues.
    """
    room = _uid()
    t1 = _register(client, "p1_" + _uid())
    t2 = _register(client, "p2_" + _uid())
    with client.websocket_connect(f"/ws/{room}?token={t1}") as ws1:
        ws1.receive_json()  # "Game started… Host is …"
        with client.websocket_connect(f"/ws/{room}?token={t2}") as ws2:
            ws1.receive_json()  # "{p2} joins… Game START!"
            ws2.receive_json()  # same broadcast to p2
            yield ws1, ws2, room


def _start(ws1, ws2, debug_code: int = None):
    """
    Send the two-step 'start' handshake and return (ws_oya, ws_ko).

    Both players must signal ready before the round begins.
    ws1 sends first (gets waiting_for_opponent), then ws2 sends to trigger
    the actual deal.  Returns players ordered by oya role.
    """
    code = str(debug_code) if debug_code else ""
    ws1.send_json({"action": "start", "card_idx": code})
    ws1.receive_json()  # waiting_for_opponent — only ws1 gets this
    ws2.send_json({"action": "start", "card_idx": code})
    msg1 = ws1.receive_json()  # deal message for ws1
    ws2.receive_json()         # deal message for ws2
    return (ws1, ws2) if msg1["is_oya"] else (ws2, ws1)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    def test_register_returns_access_token(self, client):
        resp = client.post("/api/register", json={"username": _uid(), "password": "pw"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["access_token"]

    def test_login_with_correct_credentials(self, client):
        username, password = _uid(), "hunter2"
        client.post("/api/register", json={"username": username, "password": password})
        resp = client.post("/api/login", json={"username": username, "password": password})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_login_wrong_password_returns_401(self, client):
        username = _uid()
        client.post("/api/register", json={"username": username, "password": "correct"})
        resp = client.post("/api/login", json={"username": username, "password": "wrong"})
        assert resp.status_code == 401

    def test_duplicate_username_returns_400(self, client):
        username = _uid()
        client.post("/api/register", json={"username": username, "password": "pw"})
        resp = client.post("/api/register", json={"username": username, "password": "pw2"})
        assert resp.status_code == 400

    def test_invalid_token_rejected_with_1008(self, client):
        room = _uid()
        with client.websocket_connect(f"/ws/{room}?token=not-a-valid-jwt") as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 1008

    def test_missing_token_rejected_with_1008(self, client):
        room = _uid()
        with client.websocket_connect(f"/ws/{room}?token=") as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 1008


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

class TestConnection:
    def test_first_player_receives_host_broadcast(self, client):
        room = _uid()
        token = _register(client, _uid())
        with client.websocket_connect(f"/ws/{room}?token={token}") as ws:
            msg = ws.receive_json()
        assert msg["broadcast"] is True

    def test_second_player_triggers_game_start_broadcast(self, client):
        room = _uid()
        t1 = _register(client, _uid())
        t2 = _register(client, _uid())
        with client.websocket_connect(f"/ws/{room}?token={t1}") as ws1:
            ws1.receive_json()
            with client.websocket_connect(f"/ws/{room}?token={t2}") as ws2:
                msg1 = ws1.receive_json()
                msg2 = ws2.receive_json()
        assert "Game START" in msg1["message"]
        assert msg1["message"] == msg2["message"]

    def test_third_player_rejected_room_full(self, client):
        room = _uid()
        t1, t2, t3 = _register(client, _uid()), _register(client, _uid()), _register(client, _uid())
        with client.websocket_connect(f"/ws/{room}?token={t1}") as ws1:
            ws1.receive_json()
            with client.websocket_connect(f"/ws/{room}?token={t2}") as ws2:
                ws1.receive_json()
                ws2.receive_json()
                with client.websocket_connect(f"/ws/{room}?token={t3}") as ws3:
                    with pytest.raises(WebSocketDisconnect) as exc:
                        ws3.receive_json()
                    assert exc.value.code == 1003

    def test_duplicate_player_id_rejected(self, client):
        """Same user (same UUID from JWT) cannot join the same room twice."""
        room = _uid()
        token = _register(client, _uid())
        with client.websocket_connect(f"/ws/{room}?token={token}") as ws1:
            ws1.receive_json()
            with client.websocket_connect(f"/ws/{room}?token={token}") as ws2:
                with pytest.raises(WebSocketDisconnect) as exc:
                    ws2.receive_json()
                assert exc.value.code == 1003


# ---------------------------------------------------------------------------
# Game start
# ---------------------------------------------------------------------------

class TestGameStart:
    def test_first_ready_player_waits_for_opponent(self, client):
        with _room(client) as (ws1, ws2, _):
            ws1.send_json({"action": "start", "card_idx": ""})
            reply = ws1.receive_json()
        assert reply["message"] == "waiting_for_opponent"

    def test_start_deals_14_to_oya_13_to_ko(self, client):
        with _room(client) as (ws1, ws2, _):
            ws1.send_json({"action": "start", "card_idx": ""})
            ws1.receive_json()  # waiting_for_opponent
            ws2.send_json({"action": "start", "card_idx": ""})
            msg1 = ws1.receive_json()
            msg2 = ws2.receive_json()
        assert sorted([len(msg1["hand"]), len(msg2["hand"])]) == [13, 14]

    def test_start_assigns_exactly_one_oya(self, client):
        with _room(client) as (ws1, ws2, _):
            ws1.send_json({"action": "start", "card_idx": ""})
            ws1.receive_json()
            ws2.send_json({"action": "start", "card_idx": ""})
            msg1 = ws1.receive_json()
            msg2 = ws2.receive_json()
        assert msg1["is_oya"] != msg2["is_oya"]

    def test_start_deals_only_souzu_tiles(self, client):
        """Chinitsu variant uses only the souzu (bamboo) suit."""
        with _room(client) as (ws1, ws2, _):
            ws1.send_json({"action": "start", "card_idx": ""})
            ws1.receive_json()
            ws2.send_json({"action": "start", "card_idx": ""})
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
            _, ws_ko = _start(ws1, ws2)
            ws_ko.send_json({"action": "discard", "card_idx": "0"})
            reply = ws_ko.receive_json()
        assert reply["message"] == "not_your_turn"

    def test_oya_cannot_draw_when_already_after_draw(self, client):
        """Oya starts in after_draw state; drawing again is illegal."""
        with _room(client) as (ws1, ws2, _):
            ws_oya, _ = _start(ws1, ws2)
            ws_oya.send_json({"action": "draw", "card_idx": ""})
            reply = ws_oya.receive_json()
        assert reply["message"] == "illegal_draw"

    def test_oya_cannot_ron_on_own_turn(self, client):
        """Ron is only valid after the opponent discards."""
        with _room(client) as (ws1, ws2, _):
            ws_oya, _ = _start(ws1, ws2)
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
        assert ko_result["agari"] is True
        assert ko_result["player_id"] == oya_result["player_id"]

    def test_tsumo_win_updates_point_balances(self, client):
        """After a tsumo win the result includes updated point balances for both players."""
        with _room(client) as (ws1, ws2, _):
            ws_oya, ws_ko = _start(ws1, ws2, debug_code=_DEBUG_TSUMO)
            ws_oya.send_json({"action": "tsumo", "card_idx": ""})
            oya_result = ws_oya.receive_json()
            ws_ko.receive_json()

        assert "balances" in oya_result
        assert len(oya_result["balances"]) == 2

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


# ---------------------------------------------------------------------------
# Vs CPU (solo)
# ---------------------------------------------------------------------------


class TestVsCpu:
    def test_vs_cpu_broadcast_and_single_start_deals(self, client):
        """One human + bot=1: no second WS; one start should deal (no waiting_for_opponent)."""
        room = _uid()
        token = _register(client, "solo_" + _uid())
        with client.websocket_connect(f"/ws/{room}?token={token}&bot=1") as ws:
            ws.receive_json()  # broadcast (CPU seated)
            ws.send_json({"action": "start", "card_idx": ""})
            msg = ws.receive_json()
        assert msg.get("message") != "waiting_for_opponent"
        assert "hand" in msg
        assert isinstance(msg["hand"], list)

    def test_vs_cpu_rejects_second_human(self, client):
        room = _uid()
        t1 = _register(client, "a_" + _uid())
        t2 = _register(client, "b_" + _uid())
        with client.websocket_connect(f"/ws/{room}?token={t1}&bot=1") as ws1:
            ws1.receive_json()
            with client.websocket_connect(f"/ws/{room}?token={t2}") as ws2:
                with pytest.raises(WebSocketDisconnect) as exc:
                    ws2.receive_json()
                assert exc.value.code == 1003

    @pytest.mark.parametrize("lvl", ["easy", "normal", "hard", "unknown"])
    def test_vs_cpu_level_query_is_accepted(self, client, lvl):
        room = _uid()
        token = _register(client, "solo_" + _uid())
        with client.websocket_connect(f"/ws/{room}?token={token}&bot=1&bot_level={lvl}") as ws:
            ws.receive_json()
            ws.send_json({"action": "start", "card_idx": ""})
            msg = ws.receive_json()
        assert "hand" in msg



# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


class TestReplay:
    def test_export_replay_after_round(self, client):
        with _room(client) as (ws1, ws2, _room_name):
            ws_oya, ws_ko = _start(ws1, ws2, debug_code=_DEBUG_TSUMO)
            ws_oya.send_json({"action": "tsumo", "card_idx": ""})
            ws_oya.receive_json()
            ws_ko.receive_json()

            ws_oya.send_json({"action": "export_replay", "card_idx": ""})
            msg = ws_oya.receive_json()

        assert msg.get("message") == "ok"
        assert "replay" in msg
        rep = msg["replay"]
        assert rep.get("version") == 1
        assert "initial" in rep and "events" in rep
        assert isinstance(rep["events"], list)
        assert len(rep["events"]) >= 1

    def test_build_frames_http(self, client):
        with _room(client) as (ws1, ws2, _room_name):
            ws_oya, ws_ko = _start(ws1, ws2, debug_code=_DEBUG_TSUMO)
            ws_oya.send_json({"action": "tsumo", "card_idx": ""})
            ws_oya.receive_json()
            ws_ko.receive_json()
            ws_oya.send_json({"action": "export_replay", "card_idx": ""})
            msg = ws_oya.receive_json()
            rep = msg["replay"]

        resp = client.post("/api/replay/build-frames", json=rep)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "frames" in data
        assert len(data["frames"]) >= 2
        assert data["frames"][0]["step"] == 0
        assert "hands" in data["frames"][0]

    def test_export_replay_before_start_returns_error(self, client):
        room = _uid()
        t1 = _register(client, "p1_" + _uid())
        t2 = _register(client, "p2_" + _uid())
        with client.websocket_connect(f"/ws/{room}?token={t1}") as ws1:
            ws1.receive_json()
            with client.websocket_connect(f"/ws/{room}?token={t2}") as ws2:
                ws1.receive_json()
                ws2.receive_json()
                ws1.send_json({"action": "export_replay", "card_idx": ""})
                msg = ws1.receive_json()
        assert msg.get("message") == "no_replay_available"
        assert "replay" not in msg

    def test_replay_records_draw_event(self, client):
        with _room(client) as (ws1, ws2, _room_name):
            ws_oya, ws_ko = _start(ws1, ws2)
            ws_oya.send_json({"action": "discard", "card_idx": "0"})
            ws_oya.receive_json()
            ws_ko.receive_json()
            ws_ko.send_json({"action": "skip_ron", "card_idx": ""})
            ws_oya.receive_json()
            ws_ko.receive_json()
            ws_ko.send_json({"action": "draw", "card_idx": ""})
            ws_ko.receive_json()
            ws_oya.receive_json()

            ws_oya.send_json({"action": "export_replay", "card_idx": ""})
            msg = ws_oya.receive_json()
            rep = msg["replay"]
        assert any(ev.get("action") == "draw" for ev in rep["events"])

    def test_build_frames_contains_analysis(self, client):
        with _room(client) as (ws1, ws2, _room_name):
            ws_oya, ws_ko = _start(ws1, ws2)
            ws_oya.send_json({"action": "export_replay", "card_idx": ""})
            msg = ws_oya.receive_json()
            rep = msg["replay"]
        resp = client.post("/api/replay/build-frames", json=rep)
        assert resp.status_code == 200, resp.text
        frames = resp.json()["frames"]
        assert "analysis" in frames[0]
