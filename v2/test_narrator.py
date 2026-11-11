"""Tests for the narrator and its output guard (fake LLM, no API key)."""

from types import SimpleNamespace

from engine import ActionResult
from llm_client import LLMError
from narrator import Narrator


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.sent = []

    def generate(self, contents, system_instruction, temperature):
        self.sent.append(system_instruction + contents)
        if isinstance(self.reply, Exception):
            raise self.reply
        return SimpleNamespace(text=self.reply)


CTX = {"visible_objects": ["desk", "painting"], "inventory": []}
LOCKED = ActionResult("open", False, ["The drawer is locked. It needs a key."], "locked")


def narrate(reply, result=LOCKED, player="open the drawer"):
    llm = FakeLLM(reply)
    return Narrator(llm, secrets=["4158"]).narrate(player, result, CTX), llm


def test_good_narration_is_used():
    n, _ = narrate("You tug at the drawer, but it is locked tight. It needs a key.")
    assert n.source == "llm"


def test_secret_never_sent_to_llm():
    _, llm = narrate("It is locked and needs a key.")
    assert "4158" not in llm.sent[0]


def test_leaked_secret_is_blocked():
    n, _ = narrate("The drawer is locked. By the way, the door code is 4158.")
    assert n.source == "guarded" and n.guard_reason == "secret_leak"
    assert "4158" not in n.text


def test_invented_number_is_blocked():
    n, _ = narrate("Locked. Scratched into the wood you see the number 7731.")
    assert n.guard_reason.startswith("invented_number")


def test_false_victory_is_blocked():
    n, _ = narrate("You yank the drawer and suddenly the door swings open!")
    assert n.guard_reason == "false_victory"


def test_victory_allowed_when_engine_says_escaped():
    win = ActionResult("enter_code", True, ["The door swings open. You are free!"], escaped=True)
    n, _ = narrate("With a clunk, the door swings open and you are free!", win, "4158")
    assert n.source == "llm"


def test_dropped_clue_digits_are_detected():
    books = ActionResult("examine", True, ['"Winter\'s Silence" has 8, "Autumn Leaves" has 5, "Spring Awakening" has 4 and "Summer of Fire" has 1.'])
    n, _ = narrate("You flip through the books and see some numbers.", books, "examine books")
    assert n.source == "guarded"          # LLM forgot the digits → plain facts shown
    assert "8" in n.text and "1" in n.text


def test_llm_error_falls_back_to_plain_facts():
    n, _ = narrate(LLMError("overloaded"))
    assert n.source == "fallback" and n.text == "The drawer is locked. It needs a key."


def test_system_notes_are_appended_verbatim_not_narrated():
    r = ActionResult("move", True, ["You lift the painting.", "(Only your first action was carried out.)"])
    n, llm = narrate("You lift the heavy painting from the wall.", r, "move painting and take key")
    assert "Only your first action" in n.text
    assert "Only your first action" not in llm.sent[0]


def test_inventory_and_hints_skip_the_llm():
    llm = FakeLLM("should not be called")
    n = Narrator(llm, ["4158"]).narrate("hint", ActionResult("hint", True, ["Hint: read the note."]), CTX)
    assert n.source == "plain" and llm.sent == []
