# pylint: disable=missing-module-docstring, missing-function-docstring
"""
Compact replay encoding (compact_v1) for smaller JSON / Redis payloads.

Canonical format remains version=1 with full `initial` + `events` + `display_names`.
This module converts between compact and canonical without touching game rules.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

ACTION_TO_CODE: Dict[str, int] = {
    "draw": 1,
    "discard": 2,
    "riichi": 3,
    "kan": 4,
    "tsumo": 5,
    "ron": 6,
    "skip_ron": 7,
}
CODE_TO_ACTION: Dict[int, str] = {v: k for k, v in ACTION_TO_CODE.items()}


def _ranks_str_to_tiles(s: str) -> List[str]:
    return [f"{c}s" for c in s]


def _tiles_to_ranks_str(tiles: List[str]) -> str:
    out = []
    for t in tiles:
        if not t or not str(t).endswith("s"):
            raise ValueError(f"expected sou tile, got {t!r}")
        out.append(str(t)[0])
    return "".join(out)


def compactify_initial(initial: Dict[str, Any], pids: Tuple[str, str]) -> Dict[str, Any]:
    a, b = pids
    y = _tiles_to_ranks_str(list(initial["yama"]))
    H = [_tiles_to_ranks_str(list(initial["hands"][a])), _tiles_to_ranks_str(list(initial["hands"][b]))]
    F: List[List[str]] = []
    for pid in (a, b):
        groups: List[str] = []
        for meld in initial["fuuro"][pid]:
            groups.append(_tiles_to_ranks_str([str(x) for x in meld]))
        F.append(groups)
    K: List[List[List[int]]] = []
    for pid in (a, b):
        row: List[List[int]] = []
        for card, ri in initial["kawa"][pid]:
            row.append([int(str(card)[0]), 1 if ri else 0])
        K.append(row)
    pt = [int(initial["points"][a]), int(initial["points"][b])]
    O = [bool(initial["is_oya"][a]), bool(initial["is_oya"][b])]
    P = []
    for pid in (a, b):
        f = initial["player_flags"][pid]
        P.append(
            {
                "ri": 1 if f["is_riichi"] else 0,
                "dr": 1 if f["is_daburu_riichi"] else 0,
                "rt": f.get("riichi_turn"),
                "ip": 1 if f["is_ippatsu"] else 0,
                "rs": 1 if f["is_rinshan"] else 0,
                "ft": 1 if f["is_furiten"] else 0,
                "tf": 1 if f["is_temp_furiten"] else 0,
            }
        )
    ts = initial["turn_state"]
    idx = {a: 0, b: 1}
    cp = idx[ts["current_player"]]
    no = initial.get("next_oya")
    n_idx: Optional[int]
    if no is None:
        n_idx = None
    elif no in idx:
        n_idx = idx[no]
    else:
        n_idx = None
    return {
        "y": y,
        "H": H,
        "F": F,
        "K": K,
        "pt": pt,
        "O": O,
        "P": P,
        "kt": int(initial["kyoutaku_number"]),
        "tm": int(initial["tsumi_number"]),
        "n": n_idx,
        "ts": [cp, int(ts["turn"]), int(ts["stage"])],
        "st": int(initial["status"]),
        "r": copy.deepcopy(initial.get("rules")),
    }


def expand_initial(compact_i: Dict[str, Any], pids: Tuple[str, str]) -> Dict[str, Any]:
    a, b = pids
    yama = _ranks_str_to_tiles(compact_i["y"])
    hands = {
        a: _ranks_str_to_tiles(compact_i["H"][0]),
        b: _ranks_str_to_tiles(compact_i["H"][1]),
    }
    fuuro: Dict[str, List[Tuple[str, ...]]] = {a: [], b: []}
    for j, pid in enumerate((a, b)):
        for g in compact_i["F"][j]:
            fuuro[pid].append(tuple(f"{c}s" for c in g))
    kawa: Dict[str, List[Tuple[str, bool]]] = {a: [], b: []}
    for j, pid in enumerate((a, b)):
        for r, ri in compact_i["K"][j]:
            kawa[pid].append((f"{int(r)}s", bool(ri)))
    points = {a: int(compact_i["pt"][0]), b: int(compact_i["pt"][1])}
    is_oya = {a: bool(compact_i["O"][0]), b: bool(compact_i["O"][1])}
    player_flags = {}
    for j, pid in enumerate((a, b)):
        f = compact_i["P"][j]
        player_flags[pid] = {
            "is_riichi": bool(f["ri"]),
            "is_daburu_riichi": bool(f["dr"]),
            "riichi_turn": f.get("rt"),
            "is_ippatsu": bool(f["ip"]),
            "is_rinshan": bool(f["rs"]),
            "is_furiten": bool(f["ft"]),
            "is_temp_furiten": bool(f["tf"]),
        }
    cp_idx, turn, stage = compact_i["ts"]
    current = pids[cp_idx]
    n_idx = compact_i.get("n")
    next_oya = pids[int(n_idx)] if n_idx is not None else None
    rules = compact_i.get("r")
    if rules is None:
        raise ValueError("compact initial missing rules (r)")
    return {
        "version": 1,
        "player_ids": [a, b],
        "rules": rules,
        "yama": yama,
        "hands": hands,
        "fuuro": fuuro,
        "kawa": kawa,
        "points": points,
        "is_oya": is_oya,
        "player_flags": player_flags,
        "kyoutaku_number": int(compact_i["kt"]),
        "tsumi_number": int(compact_i["tm"]),
        "next_oya": next_oya,
        "turn_state": {"current_player": current, "turn": int(turn), "stage": int(stage)},
        "status": int(compact_i["st"]),
    }


def compactify_events(events: List[Dict[str, Any]], pids: Tuple[str, str]) -> List[List[Any]]:
    idx = {pids[0]: 0, pids[1]: 1}
    out: List[List[Any]] = []
    for ev in events:
        pid = ev["player_id"]
        code = ACTION_TO_CODE[ev["action"]]
        cid = ev.get("card_idx")
        out.append([idx[pid], code, cid])
    return out


def expand_events(rows: List[List[Any]], pids: Tuple[str, str]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for row in rows:
        pi = int(row[0])
        code = int(row[1])
        cid = row[2] if len(row) > 2 else None
        ev: Dict[str, Any] = {
            "player_id": pids[pi],
            "action": CODE_TO_ACTION[int(code)],
        }
        if cid is not None:
            ev["card_idx"] = cid
        events.append(ev)
    return events


def compactify_display_names(names: Dict[str, str], pids: Tuple[str, str]) -> List[str]:
    return [names.get(pids[0], "") or "", names.get(pids[1], "") or ""]


def expand_display_names(dn: List[str], pids: Tuple[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if len(dn) > 0 and dn[0]:
        out[pids[0]] = dn[0]
    if len(dn) > 1 and dn[1]:
        out[pids[1]] = dn[1]
    return out


def compactify_v1(full: Dict[str, Any]) -> Dict[str, Any]:
    """Shrink a canonical v1 replay dict."""
    initial = full["initial"]
    pids = tuple(initial["player_ids"])
    if len(pids) != 2:
        raise ValueError("compact_v1 requires exactly two players")
    a, b = pids[0], pids[1]
    return {
        "version": 1,
        "encoding": "compact_v1",
        "p": [a, b],
        "dn": compactify_display_names(dict(full.get("display_names") or {}), (a, b)),
        "i": compactify_initial(initial, (a, b)),
        "e": compactify_events(list(full["events"]), (a, b)),
    }


def expand_compact_v1(compact: Dict[str, Any]) -> Dict[str, Any]:
    """Expand compact_v1 payload to canonical v1 for simulation."""
    p = compact["p"]
    if len(p) != 2:
        raise ValueError("compact replay requires p length 2")
    a, b = str(p[0]), str(p[1])
    return {
        "version": 1,
        "initial": expand_initial(compact["i"], (a, b)),
        "events": expand_events(list(compact["e"]), (a, b)),
        "display_names": expand_display_names(list(compact.get("dn") or []), (a, b)),
    }


def normalize_replay_for_build(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accept canonical v1 or compact_v1; return canonical v1 dict for hydrate/input loop.
    """
    if payload.get("encoding") == "compact_v1":
        return expand_compact_v1(payload)
    if int(payload.get("version", 0)) != 1:
        raise ValueError("unsupported replay version")
    return payload
