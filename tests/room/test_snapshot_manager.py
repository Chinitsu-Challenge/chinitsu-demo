"""
tests/room/test_snapshot_manager.py
SnapshotManager 测试：序列化、视角裁剪、持久化。
"""
import pytest
from tests.room.conftest import run_async

from room.snapshot_manager import SnapshotManager


# ══════════════════════════════════════════════════════════════
# 测试用快照数据
# ══════════════════════════════════════════════════════════════

def make_test_snapshot(alice_hand=None, bob_hand=None):
    """生成标准测试快照（双方各有手牌）"""
    return {
        "saved_at": 1000000.0,
        "game_status": "running",
        "turn_stage": "after_draw",
        "current_player_id": "uid-alice",
        "turn_number": 3,
        "round_no": 1,
        "round_limit": 8,
        "wall_count": 18,
        "kyoutaku_number": 0,
        "tsumi_number": 0,
        "players": {
            "uid-alice": {
                "display_name": "uid-alice",  # 注意：当前实现用 user_id 作为 display_name
                "hand": alice_hand or ["1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s", "1s", "2s", "3s", "4s"],
                "fuuro": [],
                "kawa": [["5s", False], ["3s", True]],
                "point": 150000,
                "is_oya": True,
                "is_riichi": False,
                "num_kan": 0,
            },
            "uid-bob": {
                "display_name": "uid-bob",
                "hand": bob_hand or ["1s", "3s", "5s", "7s", "9s", "2s", "4s", "6s", "8s", "1s", "2s", "3s"],
                "fuuro": [],
                "kawa": [["7s", False]],
                "point": 150000,
                "is_oya": False,
                "is_riichi": False,
                "num_kan": 0,
            },
        }
    }


# ══════════════════════════════════════════════════════════════
# build_player_view 安全性测试
# ══════════════════════════════════════════════════════════════

class TestBuildPlayerView:
    def test_my_hand_is_visible(self):
        snap = make_test_snapshot(alice_hand=["1s", "2s", "3s"])
        view = SnapshotManager.build_player_view(snap, "uid-alice")
        assert view["me"]["hand"] == ["1s", "2s", "3s"]

    def test_opponent_hand_never_exposed(self):
        """对手手牌绝不能出现在视图中"""
        snap = make_test_snapshot(bob_hand=["9s", "8s", "7s"])
        view = SnapshotManager.build_player_view(snap, "uid-alice")
        assert "hand" not in view["opponent"], "opponent.hand should NEVER be exposed!"

    def test_opponent_hand_count_visible(self):
        snap = make_test_snapshot(bob_hand=["1s", "2s"])
        view = SnapshotManager.build_player_view(snap, "uid-alice")
        assert view["opponent"]["hand_count"] == 2

    def test_bob_perspective(self):
        """从 Bob 视角：Bob 自己的手牌可见，Alice 的不可见"""
        snap = make_test_snapshot(
            alice_hand=["1s", "2s", "3s"],
            bob_hand=["9s", "8s", "7s", "6s"]
        )
        view = SnapshotManager.build_player_view(snap, "uid-bob")
        assert view["me"]["hand"] == ["9s", "8s", "7s", "6s"]
        assert "hand" not in view["opponent"]
        assert view["opponent"]["hand_count"] == 3

    def test_kawa_visible_for_both(self):
        snap = make_test_snapshot()
        view = SnapshotManager.build_player_view(snap, "uid-alice")
        assert "kawa" in view["me"]
        assert "kawa" in view["opponent"]

    def test_fuuro_visible_for_both(self):
        snap = make_test_snapshot()
        view = SnapshotManager.build_player_view(snap, "uid-alice")
        assert "fuuro" in view["me"]
        assert "fuuro" in view["opponent"]

    def test_points_visible_for_both(self):
        snap = make_test_snapshot()
        view = SnapshotManager.build_player_view(snap, "uid-alice")
        assert view["me"]["point"] == 150000
        assert view["opponent"]["point"] == 150000

    def test_game_metadata_present(self):
        snap = make_test_snapshot()
        view = SnapshotManager.build_player_view(snap, "uid-alice")
        assert view["event"] == "game_snapshot"
        assert view["broadcast"] is False
        assert view["game_status"] == "running"
        assert view["turn_stage"] == "after_draw"
        assert view["round_no"] == 1
        assert view["round_limit"] == 8
        assert view["wall_count"] == 18
        assert view["kyoutaku_number"] == 0
        assert view["current_player"] == "uid-alice"
        assert view["turn_number"] == 3

    def test_riichi_flag_visible_in_opponent(self):
        snap = make_test_snapshot()
        snap["players"]["uid-bob"]["is_riichi"] = True
        view = SnapshotManager.build_player_view(snap, "uid-alice")
        assert view["opponent"]["is_riichi"] is True

    def test_oya_flag_visible(self):
        snap = make_test_snapshot()
        view = SnapshotManager.build_player_view(snap, "uid-alice")
        assert view["me"]["is_oya"] is True
        assert view["opponent"]["is_oya"] is False


# ══════════════════════════════════════════════════════════════
# 内存存储测试
# ══════════════════════════════════════════════════════════════

class TestSnapshotStorage:
    def test_save_and_load_in_memory(self):
        """保存后能从内存读取"""
        async def inner():
            mgr = SnapshotManager()
            snap = make_test_snapshot()
            await mgr.save_snapshot("room1", snap)
            loaded = await mgr.load_snapshot("room1")
            assert loaded is not None
            assert loaded["game_status"] == "running"
            assert loaded["players"]["uid-alice"]["hand"] == snap["players"]["uid-alice"]["hand"]

        run_async(inner())

    def test_load_nonexistent_returns_none(self):
        async def inner():
            mgr = SnapshotManager()
            result = await mgr.load_snapshot("nonexistent-room")
            assert result is None

        run_async(inner())

    def test_delete_snapshot(self):
        async def inner():
            mgr = SnapshotManager()
            await mgr.save_snapshot("room1", make_test_snapshot())
            await mgr.delete_snapshot("room1")
            result = await mgr.load_snapshot("room1")
            assert result is None

        run_async(inner())

    def test_overwrite_snapshot(self):
        """重复保存应覆盖旧快照"""
        async def inner():
            mgr = SnapshotManager()
            snap1 = make_test_snapshot()
            snap1["wall_count"] = 20
            await mgr.save_snapshot("room1", snap1)

            snap2 = make_test_snapshot()
            snap2["wall_count"] = 5
            await mgr.save_snapshot("room1", snap2)

            loaded = await mgr.load_snapshot("room1")
            assert loaded["wall_count"] == 5  # 应为最新值

        run_async(inner())

    def test_multiple_rooms_independent(self):
        async def inner():
            mgr = SnapshotManager()
            snap_a = make_test_snapshot()
            snap_a["wall_count"] = 10
            snap_b = make_test_snapshot()
            snap_b["wall_count"] = 20

            await mgr.save_snapshot("room-a", snap_a)
            await mgr.save_snapshot("room-b", snap_b)

            loaded_a = await mgr.load_snapshot("room-a")
            loaded_b = await mgr.load_snapshot("room-b")
            assert loaded_a["wall_count"] == 10
            assert loaded_b["wall_count"] == 20

        run_async(inner())


# ══════════════════════════════════════════════════════════════
# serialize_game 从 ChinitsuGame 对象序列化
# ══════════════════════════════════════════════════════════════

class TestSerializeGame:
    def _make_game(self):
        """创建并启动一个含两名玩家的真实 ChinitsuGame"""
        from game import ChinitsuGame
        game = ChinitsuGame()
        game.add_player("uid-alice")
        game.add_player("uid-bob")
        game.start_new_game()
        game.state.next()  # oya 不摸牌
        game.set_running()
        return game

    def test_serialize_returns_dict(self):
        game = self._make_game()
        snap = SnapshotManager.serialize_game(game, "room1", round_no=0, round_limit=8)
        assert isinstance(snap, dict)

    def test_serialize_contains_players(self):
        game = self._make_game()
        snap = SnapshotManager.serialize_game(game, "room1")
        assert "uid-alice" in snap["players"]
        assert "uid-bob" in snap["players"]

    def test_serialize_hand_not_empty(self):
        game = self._make_game()
        snap = SnapshotManager.serialize_game(game, "room1")
        alice_hand = snap["players"]["uid-alice"]["hand"]
        bob_hand = snap["players"]["uid-bob"]["hand"]
        assert len(alice_hand) > 0
        assert len(bob_hand) > 0

    def test_serialize_wall_count(self):
        game = self._make_game()
        snap = SnapshotManager.serialize_game(game, "room1")
        assert snap["wall_count"] == len(game.yama)

    def test_serialize_game_status(self):
        game = self._make_game()
        snap = SnapshotManager.serialize_game(game, "room1")
        assert snap["game_status"] == "running"

    def test_serialize_round_info(self):
        game = self._make_game()
        snap = SnapshotManager.serialize_game(game, "room1", round_no=3, round_limit=10)
        assert snap["round_no"] == 3
        assert snap["round_limit"] == 10

    def test_view_from_serialized_game(self):
        """序列化后能正确生成玩家视图（安全检查）"""
        game = self._make_game()
        snap = SnapshotManager.serialize_game(game, "room1")
        view = SnapshotManager.build_player_view(snap, "uid-alice")
        assert "hand" not in view["opponent"], "Opponent hand must not be exposed after serialize!"
        assert view["me"]["hand"] == game.player("uid-alice").hand
