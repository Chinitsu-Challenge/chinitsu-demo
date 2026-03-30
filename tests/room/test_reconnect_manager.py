"""
tests/room/test_reconnect_manager.py
ReconnectManager 测试：断线处理、重连流程、超时回调、connection_id 保护。
"""
import pytest
from tests.room.conftest import MockWebSocket, run_async, setup_running_room, setup_two_player_room

from room.models import RoomStatus


# ══════════════════════════════════════════════════════════════
# RUNNING 状态断线
# ══════════════════════════════════════════════════════════════

class TestOnDisconnectRunning:
    def test_single_disconnect_transitions_to_reconnect(self):
        """RUNNING 中单方断线 → 房间进入 RECONNECT"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]
            assert room.status == RoomStatus.RUNNING

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            assert room.status == RoomStatus.RECONNECT

        run_async(inner())

    def test_single_disconnect_notifies_opponent(self):
        """单方断线 → 对手收到 opponent_disconnected"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            ws_bob.clear()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            msg = ws_bob.last_event("opponent_disconnected")
            assert msg is not None, "对手未收到 opponent_disconnected"

        run_async(inner())

    def test_single_disconnect_starts_reconnect_timer(self):
        """单方断线 → 启动重连计时器"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            timer_key = "reconnect:testroom:uid-alice"
            assert rm.timers.exists(timer_key) is True
            await rm.timers.cancel(timer_key)  # 清理，防止影响其他测试

        run_async(inner())

    def test_both_offline_destroys_room(self):
        """双方都断线 → 房间直接销毁"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            # Alice 先断线 → RECONNECT
            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            assert "testroom" in rm.rooms

            # Bob 再断线 → BOTH_OFFLINE → DESTROYED
            await rm.disconnect(ws_bob, "testroom", "uid-bob")

            assert "testroom" not in rm.rooms, "双方断线后房间应被销毁"

        run_async(inner())

    def test_both_offline_cancels_reconnect_timer(self):
        """双方断线时重连计时器也被取消"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            # 此时 alice 的重连计时器存在
            assert rm.timers.exists("reconnect:testroom:uid-alice")

            await rm.disconnect(ws_bob, "testroom", "uid-bob")
            # 房间销毁后计时器应已取消
            assert rm.timers.exists("reconnect:testroom:uid-alice") is False

        run_async(inner())

    def test_stale_connection_id_ignored(self):
        """旧 connection_id 的断线事件不改变房间状态"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]
            session = rm.get_session("testroom", "uid-alice")

            # 模拟新连接已建立：修改 connection_id
            session.connection_id = "new-connection-id"

            # 用旧 connection_id 触发 disconnect（通过 reconnect_mgr 直接调用）
            await rm.reconnect_mgr.on_disconnect("testroom", "uid-alice", "old-connection-id")

            # 状态应保持 RUNNING
            assert room.status == RoomStatus.RUNNING

        run_async(inner())

    def test_disconnect_marks_session_offline(self):
        """断线后 session 应标记为 offline"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            session = rm.get_session("testroom", "uid-alice")
            assert session is not None
            assert session.online is False

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# WAITING / ENDED 状态断线
# ══════════════════════════════════════════════════════════════

class TestOnDisconnectLobby:
    def test_disconnect_in_waiting_removes_player(self):
        """WAITING 中断线 → 玩家从房间移除"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            room = rm.rooms["testroom"]

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            assert "uid-alice" not in room.player_ids

        run_async(inner())

    def test_disconnect_last_player_destroys_room(self):
        """WAITING 中最后一名玩家断线 → 房间销毁"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            await rm.disconnect(ws_bob, "testroom", "uid-bob")

            assert "testroom" not in rm.rooms

        run_async(inner())

    def test_disconnect_in_waiting_no_reconnect_timer(self):
        """WAITING 断线不启动重连计时器"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            assert rm.timers.exists("reconnect:testroom:uid-alice") is False

        run_async(inner())

    def test_disconnect_in_waiting_notifies_remaining(self):
        """WAITING 中断线 → 剩余玩家收到 player_left"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            ws_bob.clear()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            msg = ws_bob.last_event("player_left")
            assert msg is not None, "剩余玩家应收到 player_left"

        run_async(inner())

    def test_disconnect_in_waiting_clears_ready_votes(self):
        """WAITING 断线后 ready 投票被清除"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()

            # Alice 先 ready
            await rm.handle_action({"action": "start", "card_idx": ""}, "testroom", "uid-alice")
            assert "uid-alice" in rm.ready_svc.get_ready_ids("testroom")

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            assert rm.ready_svc.get_ready_ids("testroom") == []

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 重连成功流程
# ══════════════════════════════════════════════════════════════

class TestOnReconnect:
    def test_reconnect_success_returns_true(self):
        """断线后重连 → on_reconnect 返回 True"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            ws_new = MockWebSocket("alice-new")
            success = await rm.reconnect_mgr.on_reconnect(
                ws_new, "testroom", "uid-alice", "Alice"
            )

            assert success is True

        run_async(inner())

    def test_reconnect_restores_running_status(self):
        """重连成功 → 房间回到 RUNNING"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            assert room.status == RoomStatus.RECONNECT

            ws_new = MockWebSocket("alice-new")
            await rm.reconnect_mgr.on_reconnect(ws_new, "testroom", "uid-alice", "Alice")

            assert room.status == RoomStatus.RUNNING

        run_async(inner())

    def test_reconnect_cancels_timer(self):
        """重连成功后计时器被取消"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            assert rm.timers.exists("reconnect:testroom:uid-alice") is True

            ws_new = MockWebSocket("alice-new")
            await rm.reconnect_mgr.on_reconnect(ws_new, "testroom", "uid-alice", "Alice")

            assert rm.timers.exists("reconnect:testroom:uid-alice") is False

        run_async(inner())

    def test_reconnect_sends_snapshot_to_reconnecting_player(self):
        """重连方收到游戏快照"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            ws_new = MockWebSocket("alice-new")
            await rm.reconnect_mgr.on_reconnect(ws_new, "testroom", "uid-alice", "Alice")

            snap = ws_new.last_event("game_snapshot")
            assert snap is not None, "重连方应收到 game_snapshot"

        run_async(inner())

    def test_reconnect_snapshot_hides_opponent_hand(self):
        """重连收到的快照中对手手牌不可见"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            ws_new = MockWebSocket("alice-new")
            await rm.reconnect_mgr.on_reconnect(ws_new, "testroom", "uid-alice", "Alice")

            snap = ws_new.last_event("game_snapshot")
            assert snap is not None
            assert "hand" not in snap.get("opponent", {}), "对手手牌绝不能暴露"

        run_async(inner())

    def test_reconnect_notifies_opponent(self):
        """重连成功 → 对手收到 opponent_reconnected"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            ws_bob.clear()

            ws_new = MockWebSocket("alice-new")
            await rm.reconnect_mgr.on_reconnect(ws_new, "testroom", "uid-alice", "Alice")

            msg = ws_bob.last_event("opponent_reconnected")
            assert msg is not None, "对手应收到 opponent_reconnected"

        run_async(inner())

    def test_reconnect_updates_session_ws(self):
        """重连后 session.ws 更新为新的 WebSocket 对象"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            ws_new = MockWebSocket("alice-new")
            await rm.reconnect_mgr.on_reconnect(ws_new, "testroom", "uid-alice", "Alice")

            session = rm.get_session("testroom", "uid-alice")
            assert session.ws is ws_new
            assert session.online is True

        run_async(inner())

    # ── 重连失败场景 ──────────────────────────────────────────

    def test_reconnect_wrong_room_fails(self):
        """重连到不存在的房间 → 返回 False"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            ws_new = MockWebSocket("alice-new")
            success = await rm.reconnect_mgr.on_reconnect(
                ws_new, "no-such-room", "uid-alice", "Alice"
            )
            assert success is False

        run_async(inner())

    def test_reconnect_wrong_user_id_fails(self):
        """不属于该房间的 user_id 重连 → 返回 False"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            ws_new = MockWebSocket("charlie")
            success = await rm.reconnect_mgr.on_reconnect(
                ws_new, "testroom", "uid-charlie", "Charlie"
            )
            assert success is False

        run_async(inner())

    def test_reconnect_already_online_fails(self):
        """已在线的玩家发起重连 → 返回 False（不是重连场景）"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()

            # Alice 目前在线（RUNNING），不应被当成重连
            ws_new = MockWebSocket("alice-new")
            success = await rm.reconnect_mgr.on_reconnect(
                ws_new, "testroom", "uid-alice", "Alice"
            )
            assert success is False

        run_async(inner())

    def test_reconnect_when_status_not_reconnect_fails(self):
        """房间不在 RECONNECT 状态时重连 → 返回 False"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_two_player_room()
            # 房间在 WAITING，不是 RECONNECT
            session = rm.get_session("testroom", "uid-alice")
            session.online = False  # 模拟离线

            ws_new = MockWebSocket("alice-new")
            success = await rm.reconnect_mgr.on_reconnect(
                ws_new, "testroom", "uid-alice", "Alice"
            )
            assert success is False

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# 重连超时回调
# ══════════════════════════════════════════════════════════════

class TestReconnectTimeout:
    def test_timeout_transitions_to_ended(self):
        """重连超时 → 房间进入 ENDED"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]
            room_id = room.room_id

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            assert room.status == RoomStatus.RECONNECT

            # 直接触发超时回调
            await rm.reconnect_mgr._on_reconnect_timeout("testroom", room_id, "uid-alice")

            assert room.status == RoomStatus.ENDED

        run_async(inner())

    def test_timeout_broadcasts_reconnect_timeout(self):
        """重连超时 → 广播 reconnect_timeout 消息"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            ws_bob.clear()

            await rm.reconnect_mgr._on_reconnect_timeout("testroom", room.room_id, "uid-alice")

            msg = ws_bob.last_event("reconnect_timeout")
            assert msg is not None, "在线方应收到 reconnect_timeout"

        run_async(inner())

    def test_timeout_sets_correct_winner_loser(self):
        """超时消息中胜者和负者正确"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            ws_bob.clear()

            await rm.reconnect_mgr._on_reconnect_timeout("testroom", room.room_id, "uid-alice")

            msg = ws_bob.last_event("reconnect_timeout")
            assert msg is not None
            assert msg["loser_id"] == "uid-alice"
            assert msg["winner_id"] == "uid-bob"

        run_async(inner())

    def test_timeout_wrong_room_id_ignored(self):
        """旧 room_id 的超时回调应被忽略"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]

            await rm.disconnect(ws_alice, "testroom", "uid-alice")
            assert room.status == RoomStatus.RECONNECT

            # 错误的 room_id
            await rm.reconnect_mgr._on_reconnect_timeout("testroom", "wrong-room-id", "uid-alice")

            # 状态不应改变
            assert room.status == RoomStatus.RECONNECT

            # 清理
            await rm.timers.cancel("reconnect:testroom:uid-alice")

        run_async(inner())

    def test_timeout_after_reconnect_ignored(self):
        """已重连成功后，超时回调不应生效"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            # 重连成功
            ws_new = MockWebSocket("alice-new")
            await rm.reconnect_mgr.on_reconnect(ws_new, "testroom", "uid-alice", "Alice")
            assert room.status == RoomStatus.RUNNING

            # 超时回调到来（太迟了）
            await rm.reconnect_mgr._on_reconnect_timeout("testroom", room.room_id, "uid-alice")

            # 状态不应改变
            assert room.status == RoomStatus.RUNNING

        run_async(inner())

    def test_timeout_nonexistent_room_no_crash(self):
        """超时回调时房间已不存在 → 不抛异常"""
        async def inner():
            from room.room_manager import RoomManager
            rm = RoomManager()

            # 直接对不存在的房间调用超时
            await rm.reconnect_mgr._on_reconnect_timeout("ghost-room", "some-id", "uid-alice")
            # 不应抛异常

        run_async(inner())

    def test_timeout_player_already_online_ignored(self):
        """超时时离线玩家已重新上线（边界情况）→ 回调被忽略"""
        async def inner():
            rm, ws_alice, ws_bob = await setup_running_room()
            room = rm.rooms["testroom"]

            await rm.disconnect(ws_alice, "testroom", "uid-alice")

            # 手动将 session 标记为在线（模拟重连刚完成但状态未来得及变化的边界场景）
            session = rm.get_session("testroom", "uid-alice")
            session.online = True

            await rm.reconnect_mgr._on_reconnect_timeout("testroom", room.room_id, "uid-alice")

            # 应该被忽略，不触发状态变化
            assert room.status == RoomStatus.RECONNECT  # 未变（因为 session.online=True 导致回调退出）

            # 清理
            await rm.timers.cancel("reconnect:testroom:uid-alice")

        run_async(inner())
