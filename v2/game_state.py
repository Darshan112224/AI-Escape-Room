"""
game_state.py — The structured memory of the game (Version 2).

In V1 the only "state" was the chat history (free text the LLM had to re-read
and interpret every turn). In V2 the state is a real Python object. It is the
single source of truth: if something is not recorded here, it did not happen.

NEW PYTHON FEATURE: @dataclass
------------------------------
`@dataclass` (from the standard library) auto-generates __init__, __repr__ and
__eq__ from the class attributes below, so we don't write boilerplate.
`field(default_factory=set)` gives each new GameState its OWN empty set.
(Writing `flags: set = set()` would share ONE set between all instances,
a classic Python bug with mutable default values.)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

GAME_DATA_PATH = Path(__file__).parent / "game_data.json"


def load_game_data(path: Path = GAME_DATA_PATH) -> dict:
    """Load the room definition (objects, rules, solution) from JSON."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class GameState:
    visible: set[str] = field(default_factory=set)     # object ids the player can see
    inventory: list[str] = field(default_factory=list)  # object ids the player carries
    flags: set[str] = field(default_factory=set)        # progress facts, e.g. "drawer_unlocked"
    wrong_attempts: int = 0                              # wrong codes entered on the keypad
    turns: int = 0
    escaped: bool = False
    log: list[dict] = field(default_factory=list)       # history of every action + outcome

    # ------------------------------------------------------------------ #
    @classmethod
    def new(cls, game_data: dict) -> "GameState":
        """
        Create the starting state from the game data.

        @classmethod: called on the class itself (GameState.new(data)), not on an
        instance. It's the usual Python pattern for "alternative constructors".
        """
        visible = {oid for oid, obj in game_data["objects"].items() if obj.get("visible")}
        return cls(visible=visible)

    # --- small, explicit mutation helpers ----------------------------- #
    # All changes go through these methods, so the state can only change in
    # well-defined ways (no LLM can write here).
    def has(self, item_id: str) -> bool:
        return item_id in self.inventory

    def add_to_inventory(self, item_id: str) -> None:
        if item_id not in self.inventory:
            self.inventory.append(item_id)

    def reveal(self, object_id: str) -> None:
        self.visible.add(object_id)

    def set_flag(self, flag: str) -> None:
        self.flags.add(flag)

    def has_flags(self, flags: list[str]) -> bool:
        return all(f in self.flags for f in flags)

    def record(self, action: str, detail: str, success: bool) -> None:
        self.log.append({"turn": self.turns, "action": action, "detail": detail, "success": success})

    # --- derived information ------------------------------------------ #
    def solved_puzzles(self, game_data: dict) -> list[str]:
        """Puzzle ids whose required flags are ALL set (computed, never stored)."""
        return [p["id"] for p in game_data["puzzles"] if self.has_flags(p["requires_flags"])]

    # --- (de)serialisation --------------------------------------------- #
    def to_dict(self) -> dict:
        """JSON-friendly dict (sets become sorted lists). Useful for saving and debugging."""
        d = asdict(self)
        d["visible"] = sorted(self.visible)
        d["flags"] = sorted(self.flags)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        # `**d` unpacks the dictionary into keyword arguments: cls(visible=..., ...)
        return cls(**{**d, "visible": set(d["visible"]), "flags": set(d["flags"])})
