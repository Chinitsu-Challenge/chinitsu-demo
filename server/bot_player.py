# pylint: disable=missing-module-docstring, missing-function-docstring
"""Heuristic CPU opponent for vs-bot rooms (no RL / LLM)."""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from mahjong.shanten import Shanten
from mahjong.tile import TilesConverter

from agari_judge import AgariJudger, get_tenpai_tiles

_shanten = Shanten()


def _hand_to_34(hand: List[str]) -> List[int]:
    hand_str = "".join(sorted(s.strip("s") for s in hand))
    return TilesConverter.string_to_34_array(sou=hand_str)


def shanten_closed(hand: List[str]) -> int:
    """Closed-hand shanten (sou only). Ignores fuuro; sufficient while bot never opens."""
    if not hand:
        return 8
    return int(_shanten.calculate_shanten(_hand_to_34(hand)))


def _other_id(game, bot_id: str) -> str:
    return game.player_ids[1 - game.player_ids.index(bot_id)]


def _tsumo_wins(game, bot_id: str, judger: AgariJudger) -> bool:
    p = game.player(bot_id)
    if p.len_hand + p.num_fuuro * 4 != 14:
        return False
    is_tenchii_tenpai = game.state.turn in [1, 2] and all(
        game.player(pid).num_kan == 0 for pid in game.player_ids
    )
    agari = judger.judge(
        p.hand,
        p.fuuro,
        p.hand[-1],
        is_tsumo=True,
        is_riichi=p.is_riichi,
        is_ippatsu=p.is_ippatsu,
        is_rinshan=p.is_rinshan,
        is_haitei=(len(game.yama) == 0),
        is_houtei=False,
        is_daburu_riichi=(p.is_riichi and p.is_daburu_riichi),
        is_tenhou=(p.is_oya and is_tenchii_tenpai),
        is_renhou=False,
        is_chiihou=((not p.is_oya) and is_tenchii_tenpai),
        is_open_riichi=False,
        is_oya=p.is_oya,
        kyoutaku_number=game.kyoutaku_number,
        tsumi_number=game.tsumi_number,
    )
    return agari.han is not None and agari.han > 0


def _ron_wins(game, bot_id: str, judger: AgariJudger) -> bool:
    p = game.player(bot_id)
    opp = game.other_player(bot_id)
    if p.len_hand + p.num_fuuro * 4 != 13 or not opp.kawa:
        return False
    if p.is_furiten or p.is_temp_furiten:
        return False
    win_card = opp.kawa[-1][0]
    tenpai_tiles = get_tenpai_tiles(p.hand, p.num_fuuro)
    kawa_cards = {k[0] for k in p.kawa}
    if any(t in kawa_cards for t in tenpai_tiles):
        return False
    is_tenchii_tenpai = game.state.turn in [1, 2] and all(
        game.player(pid).num_kan == 0 for pid in game.player_ids
    )
    agari = judger.judge(
        p.hand + [win_card],
        p.fuuro,
        win_card,
        is_tsumo=False,
        is_riichi=p.is_riichi,
        is_ippatsu=p.is_ippatsu,
        is_rinshan=False,
        is_haitei=False,
        is_houtei=(len(game.yama) == 0),
        is_daburu_riichi=(p.is_riichi and p.is_daburu_riichi),
        is_tenhou=False,
        is_renhou=is_tenchii_tenpai,
        is_chiihou=False,
        is_open_riichi=False,
        is_oya=p.is_oya,
        kyoutaku_number=game.kyoutaku_number,
        tsumi_number=game.tsumi_number,
    )
    return agari.han is not None and agari.han > 0


def _best_discard_idx(hand: List[str], n_fuuro: int) -> int:
    """Minimize shanten after discard; tie-break toward more copies of kept tiles."""
    n = len(hand)
    best_s = 99
    candidates: List[int] = []
    for i in range(n):
        rest = hand[:i] + hand[i + 1 :]
        s = shanten_closed(rest)
        if s < best_s:
            best_s = s
            candidates = [i]
        elif s == best_s:
            candidates.append(i)
    if not candidates:
        return 0
    return random.choice(candidates)

def _level_discard_idx(hand: List[str], n_fuuro: int, level: str) -> int:
    if level == "easy":
        return random.randrange(len(hand))
    if level == "normal":
        # 70% choose best-shanten discard, 30% random among all.
        if random.random() < 0.7:
            return _best_discard_idx(hand, n_fuuro)
        return random.randrange(len(hand))
    # hard
    return _best_discard_idx(hand, n_fuuro)


def _tenpai_discard_indices(hand: List[str], n_fuuro: int) -> List[int]:
    out: List[int] = []
    for i in range(len(hand)):
        rest = hand[:i] + hand[i + 1 :]
        if get_tenpai_tiles(rest, n_fuuro):
            out.append(i)
    return out


def choose_bot_action(game) -> Optional[Dict[str, Optional[int]]]:
    """
    Return {action, card_idx} for the bot's next server input, or None if the
    human should act.
    """
    # game: ChinitsuGame
    bot_id = game.bot_player_id
    if not bot_id or not getattr(game, "vs_bot", False):
        return None
    if game.is_ended or not game.is_running:
        return None

    judger = game.agari_judger
    st = game.state
    human_id = _other_id(game, bot_id)
    level = getattr(game, "bot_level", "normal")

    if st.is_after_discard and st.current_player == human_id:
        if level == "easy":
            return {"action": "skip_ron", "card_idx": None}
        if _ron_wins(game, bot_id, judger):
            return {"action": "ron", "card_idx": None}
        return {"action": "skip_ron", "card_idx": None}

    if st.current_player != bot_id:
        return None

    p = game.player(bot_id)

    if st.is_before_draw:
        return {"action": "draw", "card_idx": None}

    if st.is_after_draw:
        if _tsumo_wins(game, bot_id, judger):
            return {"action": "tsumo", "card_idx": None}

        if not p.is_riichi:
            tenpai_idxs = _tenpai_discard_indices(p.hand, p.num_fuuro)
            riichi_rate = 0.25 if level == "easy" else (0.55 if level == "normal" else 0.85)
            if tenpai_idxs and random.random() < riichi_rate:
                idx = random.choice(tenpai_idxs)
                return {"action": "riichi", "card_idx": idx}

        return {
            "action": "discard",
            "card_idx": _level_discard_idx(p.hand, p.num_fuuro, level),
        }

    return None
