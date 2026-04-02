# pylint: disable=missing-module-docstring, missing-function-docstring
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from game import ChinitsuGame, TurnState, RUNNING
from bot_player import shanten_closed
from agari_judge import get_tenpai_tiles


def _stage_to_str(stage: int) -> str:
    if stage == TurnState.BEFORE_DRAW:
        return "before_draw"
    if stage == TurnState.AFTER_DRAW:
        return "after_draw"
    if stage == TurnState.AFTER_DISCARD:
        return "after_discard"
    return "before_draw"


def hydrate_from_initial(initial: Dict[str, Any]) -> ChinitsuGame:
    """Rebuild a ChinitsuGame from a recorded post-deal snapshot."""
    pids: List[str] = list(initial["player_ids"])
    if len(pids) != 2:
        raise ValueError("replay requires exactly two player_ids")

    rules = initial.get("rules")
    g = ChinitsuGame(rules=rules)
    for pid in pids:
        g.add_player(pid)

    g.yama = list(initial["yama"])
    for pid in pids:
        pl = g.player(pid)
        pl.hand = list(initial["hands"][pid])
        pl.fuuro = [tuple(m) for m in initial["fuuro"][pid]]
        pl.kawa = [(c, bool(ri)) for c, ri in initial["kawa"][pid]]
        pl.point = int(initial["points"][pid])
        pl.is_oya = bool(initial["is_oya"][pid])
        flags = initial["player_flags"][pid]
        pl.is_riichi = bool(flags["is_riichi"])
        pl.is_daburu_riichi = bool(flags["is_daburu_riichi"])
        pl.riichi_turn = flags.get("riichi_turn")
        pl.is_ippatsu = bool(flags["is_ippatsu"])
        pl.is_rinshan = bool(flags["is_rinshan"])
        pl.is_furiten = bool(flags["is_furiten"])
        pl.is_temp_furiten = bool(flags["is_temp_furiten"])

    g.kyoutaku_number = int(initial["kyoutaku_number"])
    g.tsumi_number = int(initial["tsumi_number"])
    g.next_oya = initial.get("next_oya")
    g._ready = set()

    ts = initial["turn_state"]
    g.state = TurnState(pids)
    g.state.current_player = ts["current_player"]
    g.state.turn = int(ts["turn"])
    g.state.stage = int(ts["stage"])

    st = initial.get("status", RUNNING)
    g.status = int(st)
    return g


def _frame_from_game(
    g: ChinitsuGame,
    display_names: Dict[str, str],
    step: int,
    last_event: Optional[Dict[str, Any]],
    overlay: Dict[str, Any],
) -> Dict[str, Any]:
    pids = g.player_ids
    frame: Dict[str, Any] = {
        "step": step,
        "last_event": last_event,
        "wall_count": len(g.yama),
        "kyoutaku_number": g.kyoutaku_number,
        "current_player": g.state.current_player,
        "turn_stage": _stage_to_str(g.state.stage),
        "phase": "ended" if g.is_ended else "playing",
        "hands": {pid: list(g.player(pid).hand) for pid in pids},
        "kawa": {pid: [[c, ri] for c, ri in g.player(pid).kawa] for pid in pids},
        "fuuro": {pid: [list(t) for t in g.player(pid).fuuro] for pid in pids},
        "balances": {pid: g.player(pid).point for pid in pids},
        "is_oya": {pid: g.player(pid).is_oya for pid in pids},
        "riichi": {pid: g.player(pid).is_riichi for pid in pids},
        "player_ids": list(pids),
        "display_names": dict(display_names),
    }
    for k in ("agari", "han", "fu", "yaku", "ryukyoku", "tenpai"):
        if k in overlay:
            frame[k] = overlay[k]
    if overlay.get("agari") is not None and "point" in overlay:
        frame["agari_point"] = overlay["point"]
    analysis = _analyze_position(g)
    if analysis:
        frame["analysis"] = analysis
    return frame


def _analyze_position(g: ChinitsuGame) -> Optional[Dict[str, Any]]:
    """
    Lightweight replay analysis for the actor who is expected to discard now.
    """
    if g.is_ended:
        return None
    if g.state.stage != TurnState.AFTER_DRAW:
        return None
    pid = g.state.current_player
    if not pid:
        return None
    p = g.player(pid)
    if p.len_hand != 14:
        return None

    opts: List[Dict[str, Any]] = []
    for idx, tile in enumerate(p.hand):
        rest = p.hand[:idx] + p.hand[idx + 1 :]
        shanten = shanten_closed(rest)
        waits: List[str] = []
        wall_count = 0
        if shanten == 0:
            waits = sorted(get_tenpai_tiles(rest, p.num_fuuro))
            wall_count = sum(g.yama.count(t) for t in waits)
        opts.append(
            {
                "card_idx": idx,
                "discard": tile,
                "shanten_after": shanten,
                "waits": waits,
                "waits_in_wall": wall_count,
            }
        )

    opts.sort(key=lambda x: (x["shanten_after"], -x["waits_in_wall"], x["card_idx"]))
    top = opts[:3]
    return {
        "player_id": pid,
        "kind": "discard_recommendation",
        "summary": "Lower shanten first, then more waits left in wall.",
        "recommendations": top,
    }


def build_frames(replay: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Re-simulate a replay dict and return one frame per step (initial + after each event).
    Raises ValueError on invalid payload or simulation error.
    """
    if int(replay.get("version", 0)) != 1:
        raise ValueError("unsupported replay version")
    initial = replay["initial"]
    events: List[Dict[str, Any]] = list(replay["events"])
    names = dict(replay.get("display_names") or {})

    g = hydrate_from_initial(initial)
    frames: List[Dict[str, Any]] = []
    frames.append(_frame_from_game(g, names, 0, None, {}))

    for i, ev in enumerate(events):
        action = ev["action"]
        cid = ev.get("card_idx")
        pid = ev["player_id"]
        result = g.input(action, cid, pid)
        msg = result.get(pid, {}).get("message") if isinstance(result, dict) else None
        ok = (msg == "ok") or (msg is None and action in ("draw",))
        if pid not in result or not ok:
            raise ValueError(f"replay desync at step {i}: {result!r}")
        sample = result[g.player_ids[0]]
        overlay = {}
        for k in ("agari", "han", "fu", "point", "yaku", "ryukyoku", "tenpai"):
            if k in sample:
                overlay[k] = sample[k]
        frames.append(_frame_from_game(g, names, i + 1, ev, overlay))

    return frames
