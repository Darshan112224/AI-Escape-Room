"""
game.py — Wires the three stages of a V2 turn together:

    player text ─► ① IntentParser ─► ② GameEngine (+GameState) ─► ③ Narrator ─► reply

Keeping this outside app.py means a full turn can be tested (and reused by
other front-ends, e.g. a command-line version) without Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine import ActionResult, GameEngine
from game_state import GameState, load_game_data
from intent import Intent
from intent_parser import IntentParser
from llm_client import LLMClient
from narrator import Narration, Narrator


@dataclass
class TurnOutcome:
    reply: str
    intent: Intent
    parse_source: str
    result: ActionResult
    narration: Narration

    def debug_info(self) -> dict:
        """Everything that happened behind the scenes; shown in the UI's debug panel."""
        return {
            "1_parsed_intent": self.intent.model_dump(exclude_none=True),
            "parsed_by": self.parse_source,
            "2_engine_decision": {
                "success": self.result.success,
                "reason": self.result.reason,
                "state_changes": self.result.state_changes,
            },
            "3_narration_source": self.narration.source,
            "guard_blocked": self.narration.guard_reason or None,
        }


class EscapeRoomGame:
    def __init__(self, llm: LLMClient | None = None, game_data: dict | None = None):
        self.data = game_data or load_game_data()
        self.engine = GameEngine(self.data)
        self.parser = IntentParser(llm)
        self.narrator = Narrator(llm, secrets=[self.data["door"]["solution_code"]])
        self.llm = llm

    @property
    def opening_scene(self) -> str:
        return self.data["room"]["opening_scene"]

    def new_state(self) -> GameState:
        return GameState.new(self.data)

    def play_turn(self, state: GameState, message: str) -> TurnOutcome:
        context = self.engine.public_context(state)
        parsed = self.parser.parse(message, context["visible_objects"] + context["inventory"])   # ①
        result = self.engine.process(state, parsed.intent)                                         # ②
        narration = self.narrator.narrate(message, result, self.engine.public_context(state))      # ③
        return TurnOutcome(narration.text, parsed.intent, parsed.source, result, narration)
