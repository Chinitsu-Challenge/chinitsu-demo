from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from game import ChinitsuGame
from replay_codec import compactify_v1


@dataclass
class ReplayRecorder:
    """Room-scoped replay recorder; storage-friendly for Redis migration."""

    initial: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    display_names: Dict[str, str] = field(default_factory=dict)

    def set_display_name(self, player_id: str, display_name: str) -> None:
        if display_name:
            self.display_names[player_id] = display_name

    def start_round(self, game: ChinitsuGame) -> None:
        self.initial = game.snapshot_for_replay()
        self.events = []

    def record_action(self, player_id: str, action: str, card_idx: Optional[int]) -> None:
        rec_idx: Optional[int] = None
        if action in ("discard", "riichi", "kan") and card_idx is not None:
            rec_idx = card_idx
        self.events.append({"player_id": player_id, "action": action, "card_idx": rec_idx})

    def export(self) -> Optional[Dict[str, Any]]:
        if self.initial is None:
            return None
        return {
            "version": 1,
            "initial": self.initial,
            "events": list(self.events),
            "display_names": dict(self.display_names),
        }

    def export_compact(self) -> Optional[Dict[str, Any]]:
        full = self.export()
        if full is None:
            return None
        return compactify_v1(full)
