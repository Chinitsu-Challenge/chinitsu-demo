# bot_player.py — 启发式 CPU 对手
# 纯函数模块，不持有状态，不依赖房间层。
# 对外暴露 BOT_ID 常量和 choose_bot_action() 函数。

"""
难度说明
--------
easy  : 随机弃牌；不立直；永远不荣和（跳过）
normal: 70% 最优弃牌（向听优先）、30% 随机；
        听牌后 55% 概率立直；可以荣和
hard  : 100% 最优弃牌；听牌后 85% 概率立直；可以荣和
"""
from __future__ import annotations

import random
from typing import Optional, Dict

from mahjong.shanten import Shanten
from mahjong.tile import TilesConverter

from agari_judge import AgariJudger, get_tenpai_tiles

# Bot 固定 player_id，不对应任何真实 JWT 用户
BOT_ID = "__bot_cpu__"

_shanten_calc = Shanten()

# ── 内部工具函数 ──────────────────────────────────────────────────

def _hand_to_34(hand: list[str]) -> list[int]:
    """将 ['1s','5s',...] 转为 python-mahjong 的 34 数组（仅索子）"""
    hand_str = "".join(sorted(t[:-1] for t in hand if t.endswith("s")))
    return TilesConverter.string_to_34_array(sou=hand_str)


def _shanten(hand: list[str]) -> int:
    """计算向听数（仅闭手，无副露）"""
    if not hand:
        return 8
    return int(_shanten_calc.calculate_shanten(_hand_to_34(hand)))


def _other_id(game, bot_id: str) -> str:
    return game.player_ids[1 - game.player_ids.index(bot_id)]


def _is_tenchii_tenpai(game) -> bool:
    return game.state.turn in [1, 2] and all(
        game.player(pid).num_kan == 0 for pid in game.player_ids
    )


def _check_tsumo(game, bot_id: str) -> bool:
    """判断 bot 当前是否可以自摸"""
    p = game.player(bot_id)
    if p.len_hand + p.num_fuuro * 3 != 14:
        return False
    ttp = _is_tenchii_tenpai(game)
    agari = game.agari_judger.judge(
        p.hand, p.fuuro, p.hand[-1],
        is_tsumo=True,
        is_riichi=p.is_riichi,
        is_ippatsu=p.is_ippatsu,
        is_rinshan=p.is_rinshan,
        is_haitei=(len(game.yama) == 0),
        is_houtei=False,
        is_daburu_riichi=(p.is_riichi and p.is_daburu_riichi),
        is_tenhou=(p.is_oya and ttp),
        is_renhou=False,
        is_chiihou=(not p.is_oya and ttp),
        is_open_riichi=False,
        is_oya=p.is_oya,
        kyoutaku_number=game.kyoutaku_number,
        tsumi_number=game.tsumi_number,
    )
    return agari.han is not None and agari.han > 0


def _check_ron(game, bot_id: str) -> bool:
    """判断 bot 能否荣和对手的打牌"""
    p = game.player(bot_id)
    opp = game.other_player(bot_id)
    if p.len_hand + p.num_fuuro * 3 != 13 or not opp.kawa:
        return False
    if p.is_furiten or p.is_temp_furiten:
        return False
    win_card = opp.kawa[-1][0]
    tenpai_tiles = get_tenpai_tiles(p.hand, p.num_fuuro)
    kawa_cards = {k[0] for k in p.kawa}
    if any(t in kawa_cards for t in tenpai_tiles):
        return False
    ttp = _is_tenchii_tenpai(game)
    agari = game.agari_judger.judge(
        p.hand + [win_card], p.fuuro, win_card,
        is_tsumo=False,
        is_riichi=p.is_riichi,
        is_ippatsu=p.is_ippatsu,
        is_rinshan=False,
        is_haitei=False,
        is_houtei=(len(game.yama) == 0),
        is_daburu_riichi=(p.is_riichi and p.is_daburu_riichi),
        is_tenhou=False,
        is_renhou=ttp,
        is_chiihou=False,
        is_open_riichi=False,
        is_oya=p.is_oya,
        kyoutaku_number=game.kyoutaku_number,
        tsumi_number=game.tsumi_number,
    )
    return agari.han is not None and agari.han > 0


def _best_discard_idx(hand: list[str]) -> int:
    """最优弃牌：枚举每张牌弃出后的向听数，取向听最小的（随机打破平局）"""
    best_s = 99
    candidates: list[int] = []
    for i in range(len(hand)):
        rest = hand[:i] + hand[i + 1:]
        s = _shanten(rest)
        if s < best_s:
            best_s = s
            candidates = [i]
        elif s == best_s:
            candidates.append(i)
    return random.choice(candidates) if candidates else 0


def _tenpai_discard_indices(hand: list[str], n_fuuro: int) -> list[int]:
    """返回弃哪张牌可使手牌听牌的下标列表"""
    return [
        i for i in range(len(hand))
        if get_tenpai_tiles(hand[:i] + hand[i + 1:], n_fuuro)
    ]


# ── 公开接口 ──────────────────────────────────────────────────────

def choose_bot_action(
    game, bot_id: str, level: str
) -> Optional[Dict[str, Optional[int]]]:
    """
    根据当前游戏状态决定 bot 的下一步操作。

    返回  {action: str, card_idx: int | None}
    返回 None 表示当前不应由 bot 行动（轮到人类或游戏未运行）。
    """
    if game.is_ended or not game.is_running:
        return None

    st = game.state
    human_id = _other_id(game, bot_id)

    # ── 对手打牌后：荣和 or 跳过 ─────────────────────────────────
    if st.is_after_discard and st.current_player == human_id:
        if level == "easy":
            return {"action": "skip_ron", "card_idx": None}
        if _check_ron(game, bot_id):
            return {"action": "ron", "card_idx": None}
        return {"action": "skip_ron", "card_idx": None}

    # ── 当前不是 bot 的回合 ───────────────────────────────────────
    if st.current_player != bot_id:
        return None

    p = game.player(bot_id)

    # 摸牌阶段
    if st.is_before_draw:
        return {"action": "draw", "card_idx": None}

    # 摸牌后：自摸 / 立直 / 弃牌
    if st.is_after_draw:
        # 1. 自摸检查
        if _check_tsumo(game, bot_id):
            return {"action": "tsumo", "card_idx": None}

        # 2. 立直决策（未立直时才考虑）
        if not p.is_riichi:
            tenpai_idxs = _tenpai_discard_indices(p.hand, p.num_fuuro)
            riichi_rate = {"easy": 0.0, "normal": 0.55, "hard": 0.85}.get(level, 0.55)
            if tenpai_idxs and random.random() < riichi_rate:
                return {"action": "riichi", "card_idx": random.choice(tenpai_idxs)}

        # 3. 弃牌
        if level == "easy":
            idx = random.randrange(len(p.hand))
        elif level == "normal":
            idx = _best_discard_idx(p.hand) if random.random() < 0.7 else random.randrange(len(p.hand))
        else:  # hard
            idx = _best_discard_idx(p.hand)
        return {"action": "discard", "card_idx": idx}

    return None
