# room/snapshot_manager.py — 游戏状态快照管理
# 职责：
#   1. 从 ChinitsuGame 对象序列化出完整快照
#   2. 保存快照到 Redis（或内存兜底）
#   3. 从 Redis 加载快照
#   4. 按玩家视角裁剪快照（隐藏对手手牌）

import json
import time
import logging
from typing import Any

from redis_client import get_redis

logger = logging.getLogger("uvicorn")


class SnapshotManager:
    """游戏快照的持久化与视角裁剪"""

    def __init__(self):
        # 内存兜底存储：当 Redis 不可用时使用
        self._memory_store: dict[str, dict] = {}

    # ── 序列化：从游戏对象生成快照 ──────────────────────────────

    @staticmethod
    def serialize_game(
        game: Any,
        room_name: str,
        round_no: int = 0,
        round_limit: int = 8,
        display_names: dict[str, str] | None = None,
        owner_id: str = "",
    ) -> dict:
        """
        从 ChinitsuGame 对象序列化出完整快照。
        包含双方明文手牌（仅存储用，推送时会裁剪）。
        display_names: {user_id: 玩家昵称}，若不传则回退到 player.name（通常是 UUID）。
        """
        players_data = {}
        _names = display_names or {}
        for pid, player in game._players.items():
            players_data[pid] = {
                # 优先使用 session 中的真实昵称，回退到 player.name（可能是 UUID）
                "display_name": _names.get(pid) or getattr(player, 'name', pid),
                "hand": list(player.hand),
                "fuuro": [list(f) for f in player.fuuro],
                "kawa": [[k[0], k[1]] for k in player.kawa],
                "point": player.point,
                "is_oya": player.is_oya,
                "is_riichi": player.is_riichi,
                "num_kan": player.num_kan,
                # 以下字段用于服务重启后从快照完整重建 ChinitsuGame 对象
                "is_daburu_riichi": getattr(player, 'is_daburu_riichi', False),
                "riichi_turn":      getattr(player, 'riichi_turn', None),
                "is_ippatsu":       getattr(player, 'is_ippatsu', False),
                "is_rinshan":       getattr(player, 'is_rinshan', False),
                "is_furiten":       getattr(player, 'is_furiten', False),
                "is_temp_furiten":  getattr(player, 'is_temp_furiten', False),
            }

        # 获取回合状态（game.state 在 start_game 后才存在）
        turn_stage = "before_draw"
        current_player_id = ""
        turn_number = 0
        if hasattr(game, 'state') and game.state is not None:
            stage_map = {1: "before_draw", 2: "after_draw", 3: "after_discard"}
            turn_stage = stage_map.get(game.state.stage, "before_draw")
            current_player_id = game.state.current_player or ""
            turn_number = game.state.turn

        # 游戏级状态
        status_map = {0: "waiting", 1: "running", 2: "reconnect", 3: "ended"}
        game_status = status_map.get(game.status, "unknown")

        return {
            "saved_at": time.time(),
            "game_status": game_status,
            "turn_stage": turn_stage,
            "current_player_id": current_player_id,
            "turn_number": turn_number,
            "round_no": round_no,
            "round_limit": round_limit,
            "wall_count": len(game.yama),
            "kyoutaku_number": game.kyoutaku_number,
            "tsumi_number": game.tsumi_number,
            "players": players_data,
            "owner_id": owner_id,
            # 以下字段专用于服务重启后的游戏状态完整重建
            "yama": list(game.yama),
            "next_oya": getattr(game, 'next_oya', None),
        }

    # ── 视角裁剪：生成发给特定玩家的安全快照 ─────────────────────

    @staticmethod
    def build_player_view(snapshot: dict, viewer_id: str) -> dict:
        """
        按玩家视角裁剪快照：
        - me：完整手牌信息
        - opponent：只有 hand_count，不暴露具体手牌
        """
        players = snapshot.get("players", {})
        viewer_data = players.get(viewer_id, {})

        # 找到对手
        opponent_id = None
        opponent_data = {}
        for pid, pdata in players.items():
            if pid != viewer_id:
                opponent_id = pid
                opponent_data = pdata
                break

        me = {
            "hand": viewer_data.get("hand", []),
            "fuuro": viewer_data.get("fuuro", []),
            "kawa": viewer_data.get("kawa", []),
            "point": viewer_data.get("point", 0),
            "is_oya": viewer_data.get("is_oya", False),
            "is_riichi": viewer_data.get("is_riichi", False),
        }

        opponent = {
            "display_name": opponent_data.get("display_name", ""),
            "hand_count": len(opponent_data.get("hand", [])),
            "fuuro": opponent_data.get("fuuro", []),
            "kawa": opponent_data.get("kawa", []),
            "point": opponent_data.get("point", 0),
            "is_oya": opponent_data.get("is_oya", False),
            "is_riichi": opponent_data.get("is_riichi", False),
        }

        # ── Frontend currentPlayer convention ────────────────────────
        # Backend:  current_player_id = the active actor
        #           (in AFTER_DISCARD this is the DISCARDER)
        # Frontend: currentPlayer = who CAN ACT next
        #           (in AFTER_DISCARD this is the one who can ron/skip,
        #            i.e. the OPPONENT of the discarder)
        all_pids = list(players.keys())
        raw_current = snapshot.get("current_player_id", "")
        turn_stage = snapshot.get("turn_stage", "")

        if turn_stage == "after_discard" and raw_current and len(all_pids) == 2:
            # Flip: the one who can ron/skip is the opponent of the discarder
            frontend_current_player = next(
                (pid for pid in all_pids if pid != raw_current),
                raw_current,
            )
        else:
            frontend_current_player = raw_current

        is_owner = viewer_id == snapshot.get("owner_id", "")

        return {
            "event": "game_snapshot",
            "broadcast": False,
            "game_status": snapshot.get("game_status", ""),
            "turn_stage": turn_stage,
            "current_player": frontend_current_player,
            "opponent_id": opponent_id or "",
            "turn_number": snapshot.get("turn_number", 0),
            "round_no": snapshot.get("round_no", 0),
            "round_limit": snapshot.get("round_limit", 8),
            "wall_count": snapshot.get("wall_count", 0),
            "kyoutaku_number": snapshot.get("kyoutaku_number", 0),
            "tsumi_number": snapshot.get("tsumi_number", 0),
            "me": me,
            "opponent": opponent,
            "is_owner": is_owner,
        }

    @staticmethod
    def build_spectator_view(snapshot: dict) -> dict:
        """
        生成旁观者全知视角快照。
        与 build_player_view 的区别：
        - players 字典中两名玩家的手牌均完整暴露（无隐藏）
        - 无 me/opponent 结构，直接按 user_id 索引
        - 使用 event: spectator_snapshot（初次发送）或调用方改为 spectator_game_update（后续更新）
        """
        players = snapshot.get("players", {})
        all_pids = list(players.keys())
        raw_current = snapshot.get("current_player_id", "")
        turn_stage = snapshot.get("turn_stage", "")

        # 同 build_player_view 的 frontend currentPlayer 约定
        if turn_stage == "after_discard" and raw_current and len(all_pids) == 2:
            frontend_current_player = next(
                (pid for pid in all_pids if pid != raw_current), raw_current
            )
        else:
            frontend_current_player = raw_current

        # 旁观者看到双方完整信息（手牌不隐藏）
        spectator_players = {}
        for pid, pdata in players.items():
            spectator_players[pid] = {
                "display_name": pdata.get("display_name", ""),
                "hand":         pdata.get("hand", []),
                "fuuro":        pdata.get("fuuro", []),
                "kawa":         pdata.get("kawa", []),
                "point":        pdata.get("point", 0),
                "is_oya":       pdata.get("is_oya", False),
                "is_riichi":    pdata.get("is_riichi", False),
                "num_kan":      pdata.get("num_kan", 0),
            }

        return {
            "event":            "spectator_snapshot",
            "broadcast":        False,
            "game_status":      snapshot.get("game_status", ""),
            "turn_stage":       turn_stage,
            "current_player":   frontend_current_player,
            "turn_number":      snapshot.get("turn_number", 0),
            "round_no":         snapshot.get("round_no", 0),
            "round_limit":      snapshot.get("round_limit", 8),
            "wall_count":       snapshot.get("wall_count", 0),
            "kyoutaku_number":  snapshot.get("kyoutaku_number", 0),
            "tsumi_number":     snapshot.get("tsumi_number", 0),
            "players":          spectator_players,
        }

    # ── 持久化：保存/加载快照 ──────────────────────────────────

    async def save_snapshot(self, room_name: str, snapshot: dict) -> None:
        """保存快照到 Redis（有兜底内存存储）"""
        self._memory_store[room_name] = snapshot
        redis = get_redis()
        if redis is not None:
            try:
                await redis.set(f"snapshot:{room_name}", json.dumps(snapshot))
            except Exception as e:
                logger.warning("保存快照到 Redis 失败 [%s]: %s", room_name, e)

    async def load_snapshot(self, room_name: str) -> dict | None:
        """从 Redis 加载快照（有内存兜底）"""
        # 优先从内存获取
        if room_name in self._memory_store:
            return self._memory_store[room_name]
        # 尝试从 Redis 获取
        redis = get_redis()
        if redis is not None:
            try:
                data = await redis.get(f"snapshot:{room_name}")
                if data:
                    snapshot = json.loads(data)
                    self._memory_store[room_name] = snapshot
                    return snapshot
            except Exception as e:
                logger.warning("从 Redis 加载快照失败 [%s]: %s", room_name, e)
        return None

    async def delete_snapshot(self, room_name: str) -> None:
        """删除快照（清理用）"""
        self._memory_store.pop(room_name, None)
        redis = get_redis()
        if redis is not None:
            try:
                await redis.delete(f"snapshot:{room_name}")
            except Exception:
                pass
