"""
server/room/tests/test_room_manager.py
RoomManager 集成测试：连接管理、房间生命周期、游戏流程、比赛结束。
"""
import pytest
from helpers import MockWebSocket, run_async, setup_two_player_room, setup_running_room

from room.models import RoomStatus
from room.room_manager import RoomManager


# ══════════════════════════════════════════════════════════════
# 连接与加入
# ══════════════════════════════════════════════════════════════

class TestConnect:
    def test_first_player_creates_room(self):
        """第一个玩家连接 → 创建 WAITING 房间"""
        async def inner():
            rm = RoomManager()
            ws = MockWebSocket("alice")

            result = await rm.connect(ws, "testroom", "uid-alice", "Alice")

            assert result is True
            assert "testroom" in rm.rooms
            assert rm.rooms["testroom"].status == RoomStatus.WAITING

        run_async(inner())

    def test_creator_is_owner(self):
        """创建房间的玩家成为房主"""
        async def inner():
            rm = RoomManager()
            ws = MockWebSocket("alice")
            await rm.connect(ws, "testroom", "uid-alice", "Alice")

            room = rm.rooms["testroom"]
            session = rm.get_session("testroom", "uid-alice")
            assert room.owner_id == "uid-alice"
            assert session.is_owner is True

            await rm.timers.cancel("room_expire:testroom")

        run_async(inner())

    def test_first_player_gets_room_created_event(self):
        """第一个玩家连接后收到 room_created 事件"""
        async def inner():
            rm = RoomManager()
            ws = MockWebSocket("alice")
            await rm.connect(ws, "testroom", "uid-alice", "Alice")

            msg = ws.last_event("room_created")
            assert msg is not None
            assert msg["room_name"] == "testroom"
            assert msg["user_id"] == "uid-alice"

            await rm.timers.cancel("room_expire:testroom")

        run_async(inner())

    def test_second_player_joins_successfully(self):
        """第二个玩家连接 → 加入房间，共 2 名玩家"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            room = rm.rooms["testroom"]

            assert len(room.player_ids) == 2
            assert "uid-alice" in room.player_ids
            assert "uid-bob" in room.player_ids

        run_async(inner())

    def test_second_player_not_owner(self):
        """第二个玩家不是房主"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()

            session_bob = rm.get_session("testroom", "uid-bob")
            assert session_bob.is_owner is False

        run_async(inner())

    def test_player_joined_broadcast_on_second_connect(self):
        """第二个玩家连接 → 双方都收到 player_joined"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()

            assert ws_alice.last_event("player_joined") is not None
            assert ws_bob.last_event("player_joined") is not None

        run_async(inner())

    def test_player_joined_has_correct_count(self):
        """player_joined 消息中 player_count 为 2"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()

            msg = ws_bob.last_event("player_joined")
            assert msg["player_count"] == 2

        run_async(inner())

    def test_third_connection_becomes_spectator(self):
        """房间满员后第三个连接者自动成为旁观者（不再拒绝）"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_charlie = MockWebSocket("charlie")

            result = await rm.connect(ws_charlie, "testroom", "uid-charlie", "Charlie")

            assert result is True
            assert not ws_charlie.closed
            # 进入旁观者列表而非玩家列表
            assert rm._get_spectator("testroom", "uid-charlie") is not None
            assert "uid-charlie" not in rm.sessions.get("testroom", {})

        run_async(inner())

    def test_duplicate_online_user_rejected(self):
        """相同 user_id 且已在线时被拒绝"""
        async def inner():
            rm = RoomManager()
            ws1 = MockWebSocket("alice")
            await rm.connect(ws1, "testroom", "uid-alice", "Alice")

            ws2 = MockWebSocket("alice-dup")
            result = await rm.connect(ws2, "testroom", "uid-alice", "Alice")

            assert result is False
            assert ws2.close_code == 1003

            await rm.timers.cancel("room_expire:testroom")

        run_async(inner())

    def test_invalid_room_name_empty_rejected(self):
        """空字符串房间名被拒绝"""
        async def inner():
            rm = RoomManager()
            ws = MockWebSocket("alice")

            result = await rm.connect(ws, "", "uid-alice", "Alice")

            assert result is False

        run_async(inner())

    def test_invalid_room_name_too_long_rejected(self):
        """超长房间名（>20字符）被拒绝"""
        async def inner():
            rm = RoomManager()
            ws = MockWebSocket("alice")
            long_name = "a" * 21

            result = await rm.connect(ws, long_name, "uid-alice", "Alice")

            assert result is False

        run_async(inner())

    def test_room_has_expiry_timer(self):
        """创建房间后启动过期计时器"""
        async def inner():
            rm = RoomManager()
            ws = MockWebSocket("alice")
            await rm.connect(ws, "testroom", "uid-alice", "Alice")

            assert rm.timers.exists("room_expire:testroom") is True
            await rm.timers.cancel("room_expire:testroom")

        run_async(inner())

    def test_session_created_for_player(self):
        """连接后为玩家创建 session"""
        async def inner():
            rm = RoomManager()
            ws = MockWebSocket("alice")
            await rm.connect(ws, "testroom", "uid-alice", "Alice")

            session = rm.get_session("testroom", "uid-alice")
            assert session is not None
            assert session.online is True
            assert session.display_name == "Alice"

            await rm.timers.cancel("room_expire:testroom")

        run_async(inner())

    def test_multiple_rooms_independent(self):
        """不同房间互相独立"""
        async def inner():
            rm = RoomManager()
            ws1 = MockWebSocket("alice")
            ws2 = MockWebSocket("bob")

            await rm.connect(ws1, "room-a", "uid-alice", "Alice")
            await rm.connect(ws2, "room-b", "uid-bob", "Bob")

            assert len(rm.rooms["room-a"].player_ids) == 1
            assert len(rm.rooms["room-b"].player_ids) == 1

            await rm.timers.cancel("room_expire:room-a")
            await rm.timers.cancel("room_expire:room-b")

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# WAITING 状态操作
# ══════════════════════════════════════════════════════════════

class TestWaitingActions:
    def test_start_with_one_player_returns_error(self):
        """只有 1 名玩家时 start 返回错误"""
        async def inner():
            rm = RoomManager()
            ws = MockWebSocket("alice")
            await rm.connect(ws, "testroom", "uid-alice", "Alice")
            ws.clear()

            await rm.handle_action({"action": "start", "card_idx": ""}, "testroom", "uid-alice")

            err = ws.last_event("error")
            assert err is not None

            await rm.timers.cancel("room_expire:testroom")

        run_async(inner())

    def test_first_start_broadcasts_ready_changed(self):
        """第一个玩家 start → 广播 start_ready_changed（all_ready=False）"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_alice.clear()
            ws_bob.clear()

            await rm.handle_action({"action": "start", "card_idx": ""}, "testroom", "uid-alice")

            msg = ws_alice.last_event("start_ready_changed")
            assert msg is not None
            assert "uid-alice" in msg["ready_user_ids"]
            assert msg["all_ready"] is False

        run_async(inner())

    def test_both_start_transitions_to_running(self):
        """双方都 start → 房间进入 RUNNING"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            assert rm.rooms["testroom"].status == RoomStatus.RUNNING

        run_async(inner())

    def test_both_start_sends_game_started(self):
        """双方都 start → 各自收到 game_started 事件"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            assert ws_alice.last_event("game_started") is not None
            assert ws_bob.last_event("game_started") is not None

        run_async(inner())

    def test_game_started_has_hand(self):
        """game_started 消息包含手牌"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            msg = ws_alice.last_event("game_started")
            assert "hand" in msg
            assert len(msg["hand"]) > 0

        run_async(inner())

    def test_game_started_has_wall_count(self):
        """game_started 消息包含 wall_count"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            msg = ws_alice.last_event("game_started")
            assert "wall_count" in msg
            assert msg["wall_count"] > 0

        run_async(inner())

    def test_cancel_start_removes_ready(self):
        """cancel_start → 玩家从 ready 列表移除"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()

            await rm.handle_action({"action": "start", "card_idx": ""}, "testroom", "uid-alice")
            assert "uid-alice" in rm.ready_svc.get_ready_ids("testroom")

            ws_alice.clear()
            ws_bob.clear()
            await rm.handle_action({"action": "cancel_start", "card_idx": ""}, "testroom", "uid-alice")

            msg = ws_alice.last_event("start_ready_changed")
            assert msg is not None
            assert "uid-alice" not in msg.get("ready_user_ids", [])

        run_async(inner())

    def test_game_action_in_waiting_returns_error(self):
        """WAITING 中发出游戏操作 → 返回 game_not_started 错误"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_alice.clear()

            await rm.handle_action({"action": "draw", "card_idx": ""}, "testroom", "uid-alice")

            err = ws_alice.last_event("error")
            assert err is not None
            assert err["code"] == "game_not_started"

        run_async(inner())

    def test_debug_code_starts_game(self):
        """使用 debug_code 114514 启动游戏"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room(debug_code=114514)

            assert rm.rooms["testroom"].status == RoomStatus.RUNNING

        run_async(inner())

    def test_game_creates_game_instance(self):
        """游戏启动后 games 中有实例"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            assert "testroom" in rm.games
            assert rm.games["testroom"] is not None

        run_async(inner())

    def test_snapshot_saved_after_start(self):
        """游戏启动后快照被保存"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            snap = await rm.snapshot_mgr.load_snapshot("testroom")
            assert snap is not None
            assert snap["game_status"] == "running"

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# RUNNING 状态操作
# ══════════════════════════════════════════════════════════════

class TestRunningActions:
    def test_game_paused_error_in_reconnect_state(self):
        """RECONNECT 状态中操作 → 返回 game_paused 错误"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            ws_bob.clear()

            await rm.handle_action({"action": "draw", "card_idx": ""}, "testroom", "uid-bob")

            err = ws_bob.last_event("error")
            assert err is not None
            assert err["code"] == "game_paused"

        run_async(inner())

    def test_start_new_when_round_not_ended_error(self):
        """游戏进行中发出 start_new → 返回 round_not_ended 错误"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            ws_alice.clear()

            await rm.handle_action({"action": "start_new", "card_idx": ""}, "testroom", "uid-alice")

            err = ws_alice.last_event("error")
            assert err is not None
            assert err["code"] == "round_not_ended"

        run_async(inner())

    def test_unknown_action_in_running_error(self):
        """RUNNING 中未知操作 → 返回错误"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            ws_alice.clear()

            await rm.handle_action({"action": "invalid_action", "card_idx": ""}, "testroom", "uid-alice")

            err = ws_alice.last_event("error")
            assert err is not None

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# ENDED 状态操作
# ══════════════════════════════════════════════════════════════

class TestEndedActions:
    @staticmethod
    def _force_ended(rm, room_name="testroom"):
        rm.rooms[room_name].status = RoomStatus.ENDED

    def test_end_game_destroys_room(self):
        """ENDED 中发送 end_game → 房间被销毁"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            self._force_ended(rm)

            await rm.handle_action({"action": "end_game", "card_idx": ""}, "testroom", "uid-alice")

            assert "testroom" not in rm.rooms

        run_async(inner())

    def test_end_game_broadcasts_room_closed(self):
        """end_game → 广播 room_closed"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            self._force_ended(rm)

            ws_alice.clear()
            ws_bob.clear()
            await rm.handle_action({"action": "end_game", "card_idx": ""}, "testroom", "uid-alice")

            alice_msg = ws_alice.last_event("room_closed")
            bob_msg = ws_bob.last_event("room_closed")
            assert alice_msg is not None or bob_msg is not None

        run_async(inner())

    def test_continue_single_player_not_all(self):
        """ENDED 中只有一方 continue → all_continue=False"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            self._force_ended(rm)

            ws_alice.clear()
            ws_bob.clear()
            await rm.handle_action({"action": "continue_game", "card_idx": ""}, "testroom", "uid-alice")

            msg = ws_alice.last_event("continue_vote_changed")
            assert msg is not None
            assert msg["all_continue"] is False

        run_async(inner())

    def test_both_continue_returns_to_waiting(self):
        """双方都 continue → 房间回到 WAITING"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            self._force_ended(rm)

            await rm.handle_action({"action": "continue_game", "card_idx": ""}, "testroom", "uid-alice")
            await rm.handle_action({"action": "continue_game", "card_idx": ""}, "testroom", "uid-bob")

            assert rm.rooms["testroom"].status == RoomStatus.WAITING

        run_async(inner())

    def test_both_continue_resets_round_no(self):
        """双方 continue 后 round_no 重置为 0"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            rm.rooms["testroom"].round_no = 5
            self._force_ended(rm)

            await rm.handle_action({"action": "continue_game", "card_idx": ""}, "testroom", "uid-alice")
            await rm.handle_action({"action": "continue_game", "card_idx": ""}, "testroom", "uid-bob")

            assert rm.rooms["testroom"].round_no == 0

        run_async(inner())

    def test_both_continue_clears_game_instance(self):
        """双方 continue 后旧游戏实例被清理"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            self._force_ended(rm)

            await rm.handle_action({"action": "continue_game", "card_idx": ""}, "testroom", "uid-alice")
            await rm.handle_action({"action": "continue_game", "card_idx": ""}, "testroom", "uid-bob")

            assert "testroom" not in rm.games

        run_async(inner())

    def test_start_in_ended_maps_to_continue(self):
        """ENDED 中发送 start → 等效于 continue_game"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            self._force_ended(rm)

            ws_alice.clear()
            ws_bob.clear()
            await rm.handle_action({"action": "start", "card_idx": ""}, "testroom", "uid-alice")

            msg = ws_alice.last_event("continue_vote_changed")
            assert msg is not None

        run_async(inner())

    def test_game_action_in_ended_returns_error(self):
        """ENDED 中发出游戏操作 → 返回错误"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            self._force_ended(rm)

            ws_alice.clear()
            await rm.handle_action({"action": "draw", "card_idx": ""}, "testroom", "uid-alice")

            err = ws_alice.last_event("error")
            assert err is not None

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 房间清理
# ══════════════════════════════════════════════════════════════

class TestCleanup:
    def test_cleanup_removes_room_from_memory(self):
        """cleanup_room 清除内存中的房间、session、games"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            room = rm.rooms["testroom"]

            await rm.cleanup_room("testroom", room.room_id, "test")

            assert "testroom" not in rm.rooms
            assert "testroom" not in rm.sessions

        run_async(inner())

    def test_cleanup_closes_all_websockets(self):
        """cleanup_room 关闭所有 WebSocket 连接"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            room = rm.rooms["testroom"]

            await rm.cleanup_room("testroom", room.room_id, "test")

            assert ws_alice.closed is True
            assert ws_bob.closed is True

        run_async(inner())

    def test_cleanup_cancels_timers(self):
        """cleanup_room 取消所有定时器"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            room = rm.rooms["testroom"]

            assert rm.timers.exists("room_expire:testroom") is True
            await rm.cleanup_room("testroom", room.room_id, "test")

            assert rm.timers.exists("room_expire:testroom") is False

        run_async(inner())

    def test_cleanup_wrong_room_id_skipped(self):
        """cleanup_room 使用错误 room_id 时跳过（幂等保护）"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()

            await rm.cleanup_room("testroom", "wrong-room-id", "test")

            assert "testroom" in rm.rooms

        run_async(inner())

    def test_cleanup_nonexistent_room_no_crash(self):
        """cleanup_room 对不存在的房间不抛异常"""
        async def inner():
            rm = RoomManager()
            await rm.cleanup_room("ghost-room", "ghost-id", "test")

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 房间过期
# ══════════════════════════════════════════════════════════════

class TestRoomExpiry:
    def test_expiry_callback_destroys_room(self):
        """_on_room_expired 使用正确 room_id → 房间销毁"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            room = rm.rooms["testroom"]
            room_id = room.room_id

            await rm._on_room_expired("testroom", room_id)

            assert "testroom" not in rm.rooms

        run_async(inner())

    def test_expiry_callback_wrong_id_ignored(self):
        """_on_room_expired 使用错误 room_id → 忽略"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()

            await rm._on_room_expired("testroom", "wrong-id")

            assert "testroom" in rm.rooms

        run_async(inner())

    def test_expiry_broadcasts_room_expired(self):
        """房间到期时广播 room_expired 消息"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            room = rm.rooms["testroom"]

            ws_alice.clear()
            ws_bob.clear()
            await rm._on_room_expired("testroom", room.room_id)

            alice_msg = ws_alice.last_event("room_expired")
            bob_msg = ws_bob.last_event("room_expired")
            assert alice_msg is not None or bob_msg is not None

        run_async(inner())

    def test_expiry_nonexistent_room_no_crash(self):
        """_on_room_expired 对不存在的房间不抛异常"""
        async def inner():
            rm = RoomManager()
            await rm._on_room_expired("ghost-room", "ghost-id")

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 完整重连流程集成测试
# ══════════════════════════════════════════════════════════════

class TestReconnectIntegration:
    def test_full_reconnect_via_connect(self):
        """通过 connect() 触发重连（RECONNECT 状态下重新连接）"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            assert room.status == RoomStatus.RECONNECT

            ws_new = MockWebSocket("alice-new")
            result = await rm.connect(ws_new, "testroom", "uid-alice", "Alice")

            assert result is True
            assert room.status == RoomStatus.RUNNING

        run_async(inner())

    def test_reconnect_via_connect_sends_snapshot(self):
        """通过 connect() 重连后，重连方收到快照"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            ws_new = MockWebSocket("alice-new")
            await rm.connect(ws_new, "testroom", "uid-alice", "Alice")

            snap = ws_new.last_event("game_snapshot")
            assert snap is not None

        run_async(inner())

    def test_status_is_running_after_reconnect(self):
        """重连成功后房间状态为 RUNNING"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            ws_new = MockWebSocket("alice-new")
            await rm.connect(ws_new, "testroom", "uid-alice", "Alice")

            assert rm.rooms["testroom"].status == RoomStatus.RUNNING

        run_async(inner())
