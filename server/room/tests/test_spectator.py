"""
server/room/tests/test_spectator.py
旁观者模式测试：加入、断线、动作拦截、快照推送、房间清理。
"""
import pytest
from helpers import MockWebSocket, run_async, setup_two_player_room, setup_running_room

from room.models import RoomStatus, MAX_SPECTATORS_PER_ROOM


# ══════════════════════════════════════════════════════════════
# 辅助：连接一名旁观者到满员房间
# ══════════════════════════════════════════════════════════════

async def add_spectator(rm, room_name: str, user_id: str = "uid-spec", display_name: str = "Spec") -> MockWebSocket:
    ws = MockWebSocket(user_id)
    await rm.connect(ws, room_name, user_id, display_name)
    return ws


# ══════════════════════════════════════════════════════════════
# 旁观者加入
# ══════════════════════════════════════════════════════════════

class TestSpectatorJoin:
    def test_spectator_joins_full_room(self):
        """满员房间连接 → 自动成为旁观者，连接不被关闭"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_spec = await add_spectator(rm, "testroom")
            assert not ws_spec.closed, "旁观者连接不应被关闭"
            assert rm._get_spectator("testroom", "uid-spec") is not None

        run_async(inner())

    def test_spectator_not_added_to_player_sessions(self):
        """旁观者不进入 sessions（玩家会话）"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            await add_spectator(rm, "testroom")
            assert "uid-spec" not in rm.sessions.get("testroom", {})

        run_async(inner())

    def test_spectator_count_increases(self):
        """多名旁观者加入，计数递增"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            await add_spectator(rm, "testroom", "uid-spec1", "Spec1")
            await add_spectator(rm, "testroom", "uid-spec2", "Spec2")
            assert len(rm.spectators.get("testroom", {})) == 2

        run_async(inner())

    def test_players_receive_spectator_joined(self):
        """旁观者加入后，玩家收到 spectator_joined 事件"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_alice.clear()
            ws_bob.clear()
            await add_spectator(rm, "testroom")
            assert ws_alice.last_event("spectator_joined") is not None
            assert ws_bob.last_event("spectator_joined") is not None

        run_async(inner())

    def test_spectator_receives_waiting_snapshot_when_no_game(self):
        """WAITING 状态加入 → 旁观者收到 spectator_snapshot（无游戏状态）"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_spec = await add_spectator(rm, "testroom")
            snap = ws_spec.last_event("spectator_snapshot")
            assert snap is not None
            assert snap["game_status"] == "waiting"

        run_async(inner())

    def test_spectator_receives_game_snapshot_during_running(self):
        """RUNNING 状态加入 → 旁观者收到含双方手牌的 spectator_snapshot"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            ws_spec = await add_spectator(rm, "testroom")
            snap = ws_spec.last_event("spectator_snapshot")
            assert snap is not None
            assert snap.get("game_status") in ("running", "ended")
            # 旁观者能看到 players 字典（含双方完整数据）
            assert "players" in snap
            assert len(snap["players"]) == 2
            for pid, pdata in snap["players"].items():
                assert "hand" in pdata, f"旁观者应能看到玩家 {pid} 的手牌"

        run_async(inner())

    def test_spectator_joined_contains_spectator_count(self):
        """spectator_joined 事件包含正确的旁观者数量"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_alice.clear()
            await add_spectator(rm, "testroom", "uid-spec1", "S1")
            msg = ws_alice.last_event("spectator_joined")
            assert msg["spectator_count"] == 1

            ws_alice.clear()
            await add_spectator(rm, "testroom", "uid-spec2", "S2")
            msg = ws_alice.last_event("spectator_joined")
            assert msg["spectator_count"] == 2

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 旁观者数量上限
# ══════════════════════════════════════════════════════════════

class TestSpectatorLimit:
    def test_spectator_room_full_closes_connection(self):
        """旁观者席位满员后新旁观者连接被拒绝（连接被关闭）"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()

            # 填满席位
            for i in range(MAX_SPECTATORS_PER_ROOM):
                await add_spectator(rm, "testroom", f"uid-spec-{i}", f"Spec{i}")

            # 再来一个应被拒绝
            ws_overflow = MockWebSocket("uid-overflow")
            await rm.connect(ws_overflow, "testroom", "uid-overflow", "Overflow")
            assert ws_overflow.closed, "超出上限的旁观者连接应被关闭"
            assert ws_overflow.close_reason == "spectator_room_full"

        run_async(inner())

    def test_spectator_count_does_not_exceed_limit(self):
        """被拒绝后旁观者数量不超过上限"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            for i in range(MAX_SPECTATORS_PER_ROOM):
                await add_spectator(rm, "testroom", f"uid-spec-{i}", f"Spec{i}")

            await add_spectator(rm, "testroom", "uid-overflow", "Overflow")
            assert len(rm.spectators.get("testroom", {})) == MAX_SPECTATORS_PER_ROOM

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 旁观者断线
# ══════════════════════════════════════════════════════════════

class TestSpectatorDisconnect:
    def test_spectator_disconnect_removes_from_store(self):
        """旁观者断线后从 spectators 中移除"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_spec = await add_spectator(rm, "testroom")
            assert rm._get_spectator("testroom", "uid-spec") is not None

            await rm.disconnect(ws_spec, "testroom", "uid-spec")
            assert rm._get_spectator("testroom", "uid-spec") is None

        run_async(inner())

    def test_spectator_disconnect_does_not_change_room_status(self):
        """旁观者断线不影响房间状态"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]
            ws_spec = await add_spectator(rm, "testroom")

            await rm.disconnect(ws_spec, "testroom", "uid-spec")
            assert room.status == RoomStatus.RUNNING

        run_async(inner())

    def test_spectator_disconnect_does_not_trigger_reconnect_timer(self):
        """旁观者断线不启动重连计时器"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            ws_spec = await add_spectator(rm, "testroom")

            await rm.disconnect(ws_spec, "testroom", "uid-spec")
            assert not rm.timers.exists("reconnect:testroom:uid-spec")

        run_async(inner())

    def test_spectator_left_broadcast_on_disconnect(self):
        """旁观者断线 → 玩家收到 spectator_left 事件"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_spec = await add_spectator(rm, "testroom")
            ws_alice.clear()
            ws_bob.clear()

            await rm.disconnect(ws_spec, "testroom", "uid-spec")
            assert ws_alice.last_event("spectator_left") is not None
            assert ws_bob.last_event("spectator_left") is not None

        run_async(inner())

    def test_spectator_left_spectator_count(self):
        """spectator_left 包含正确的剩余旁观者数量"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_spec1 = await add_spectator(rm, "testroom", "uid-spec1", "S1")
            await add_spectator(rm, "testroom", "uid-spec2", "S2")
            ws_alice.clear()

            await rm.disconnect(ws_spec1, "testroom", "uid-spec1")
            msg = ws_alice.last_event("spectator_left")
            assert msg is not None
            assert msg["spectator_count"] == 1  # S2 还在

        run_async(inner())

    def test_player_disconnect_does_not_remove_spectator(self):
        """玩家断线不影响旁观者会话"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            await add_spectator(rm, "testroom")

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            assert rm._get_spectator("testroom", "uid-spec") is not None

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 旁观者动作拦截
# ══════════════════════════════════════════════════════════════

class TestSpectatorActionForbidden:
    def test_spectator_action_returns_error(self):
        """旁观者发送任意 action → 收到 spectator_action_forbidden 错误"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            ws_spec = await add_spectator(rm, "testroom")
            ws_spec.clear()

            await rm.handle_action({"action": "draw", "card_idx": ""}, "testroom", "uid-spec")
            err = ws_spec.last_event("error")
            assert err is not None
            assert err["code"] == "spectator_action_forbidden"

        run_async(inner())

    def test_spectator_action_does_not_affect_game(self):
        """旁观者 action 不影响游戏状态"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]
            ws_spec = await add_spectator(rm, "testroom")

            await rm.handle_action({"action": "draw", "card_idx": ""}, "testroom", "uid-spec")
            assert room.status == RoomStatus.RUNNING

        run_async(inner())

    def test_spectator_cannot_vote_start(self):
        """旁观者不能发送 start action（WAITING 状态）"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_spec = await add_spectator(rm, "testroom")
            ws_spec.clear()

            await rm.handle_action({"action": "start", "card_idx": ""}, "testroom", "uid-spec")
            err = ws_spec.last_event("error")
            assert err is not None
            assert err["code"] == "spectator_action_forbidden"

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 旁观者全知视角（快照内容）
# ══════════════════════════════════════════════════════════════

class TestSpectatorView:
    def test_spectator_sees_both_hands(self):
        """旁观者视角包含双方完整手牌"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            ws_spec = await add_spectator(rm, "testroom")
            snap = ws_spec.last_event("spectator_snapshot")
            assert snap is not None
            for pid, pdata in snap["players"].items():
                assert isinstance(pdata["hand"], list)
                assert len(pdata["hand"]) > 0, f"旁观者应看到 {pid} 的手牌"

        run_async(inner())

    def test_player_opponent_hand_still_hidden(self):
        """玩家收到的快照中对手手牌仍然隐藏（旁观者不影响玩家视角）"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            await add_spectator(rm, "testroom")

            # 触发一次断线重连以获取 game_snapshot
            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            ws_new = MockWebSocket("alice-new")
            await rm.reconnect_mgr.on_reconnect(ws_new, "testroom", "uid-alice", "Alice")

            snap = ws_new.last_event("game_snapshot")
            assert snap is not None
            # 对手视角只有 hand_count，没有 hand
            assert "hand" not in snap.get("opponent", {}), "玩家视角对手手牌不能暴露"

        run_async(inner())

    def test_spectator_game_update_sent_after_game_action(self):
        """游戏动作后旁观者收到 spectator_game_update"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room(debug_code=114514)
            ws_spec = await add_spectator(rm, "testroom")
            ws_spec.clear()

            # 执行一次 draw 动作（debug 牌局中庄家已在 AFTER_DRAW）
            await rm.handle_action({"action": "discard", "card_idx": "0"}, "testroom", "uid-alice")

            update = ws_spec.last_event("spectator_game_update")
            assert update is not None, "旁观者应在游戏动作后收到 spectator_game_update"

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 一人一房间限制对旁观者的约束
# ══════════════════════════════════════════════════════════════

class TestSpectatorOneRoomRestriction:
    def test_spectator_cannot_join_second_room(self):
        """已在旁观一个房间的用户不能再旁观另一个房间"""
        async def inner():
            rm, ws_a1, ws_b1 = await setup_two_player_room("room1")
            # 在 room2 也建满员
            ws_a2 = MockWebSocket("uid-a2")
            ws_b2 = MockWebSocket("uid-b2")
            await rm.connect(ws_a2, "room2", "uid-a2", "A2")
            await rm.connect(ws_b2, "room2", "uid-b2", "B2")

            # uid-spec 加入 room1 旁观
            ws_spec = MockWebSocket("uid-spec")
            await rm.connect(ws_spec, "room1", "uid-spec", "Spec")
            assert not ws_spec.closed

            # uid-spec 再试图加入 room2 → 应被拒绝
            ws_spec2 = MockWebSocket("uid-spec")
            await rm.connect(ws_spec2, "room2", "uid-spec", "Spec")
            assert ws_spec2.closed
            assert ws_spec2.close_reason.startswith("already_in_room")

        run_async(inner())

    def test_player_cannot_spectate_another_room(self):
        """已是某房间玩家的用户不能旁观另一个满员房间"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room("room1")
            # room2 建满员
            ws_a2 = MockWebSocket("uid-a2")
            ws_b2 = MockWebSocket("uid-b2")
            await rm.connect(ws_a2, "room2", "uid-a2", "A2")
            await rm.connect(ws_b2, "room2", "uid-b2", "B2")

            # uid-alice（room1 的玩家）试图旁观 room2
            ws_try = MockWebSocket("uid-alice")
            await rm.connect(ws_try, "room2", "uid-alice", "Alice")
            assert ws_try.closed
            assert ws_try.close_reason.startswith("already_in_room")

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 房间清理时旁观者连接关闭
# ══════════════════════════════════════════════════════════════

class TestSpectatorCleanup:
    def test_spectator_connection_closed_on_room_cleanup(self):
        """房间销毁时旁观者连接被关闭"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            ws_spec = await add_spectator(rm, "testroom")
            room = rm.rooms["testroom"]

            # 触发房间销毁
            await rm.cleanup_room("testroom", room.room_id, "test_cleanup")
            assert ws_spec.closed, "房间销毁后旁观者连接应关闭"

        run_async(inner())

    def test_spectators_cleared_from_store_on_cleanup(self):
        """房间销毁后 spectators 存储被清理"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            await add_spectator(rm, "testroom")
            room = rm.rooms["testroom"]

            await rm.cleanup_room("testroom", room.room_id, "test_cleanup")
            assert "testroom" not in rm.spectators

        run_async(inner())
