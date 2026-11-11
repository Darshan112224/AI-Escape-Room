"""
Unit tests for game_master.py, run with:  pytest v1

We use a FAKE Gemini client instead of the real one ("mocking"), so these tests:
  - need no API key or internet,
  - are fast and always give the same result.
"""

from types import SimpleNamespace

import pytest
from google.genai import errors

import game_master
from game_master import GameMaster, GameMasterError


class FakeModels:
    """Pretends to be `client.models`. Returns pre-programmed replies or errors."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(contents)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


def make_gm(*outcomes):
    fake_client = SimpleNamespace(models=FakeModels(outcomes))
    return GameMaster(api_key="test", client=fake_client), fake_client.models


HISTORY = [
    {"role": "assistant", "content": "You wake up in a library."},
    {"role": "user", "content": "I examine the painting."},
]


def test_history_is_converted_with_start_message():
    contents = GameMaster._to_gemini_contents(HISTORY)
    # synthetic "Start the game." + opening scene + player message
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[2].parts[0].text == "I examine the painting."


def test_respond_returns_reply_and_sends_full_history():
    gm, models = make_gm("The frame looks loose.")
    assert gm.respond(HISTORY) == "The frame looks loose."
    assert len(models.calls[0]) == 3  # whole conversation was sent


def test_escape_marker_detected_and_removed():
    escaped, text = GameMaster.check_escape("The door swings open! [ESCAPED]")
    assert escaped is True
    assert "[ESCAPED]" not in text


def test_no_escape_without_marker():
    escaped, _ = GameMaster.check_escape("The keypad buzzes red.")
    assert escaped is False


def test_retries_on_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr(game_master.time, "sleep", lambda s: None)  # skip waiting
    gm, models = make_gm(errors.APIError(429, {}), "Recovered reply")
    assert gm.respond(HISTORY) == "Recovered reply"
    assert len(models.calls) == 2


def test_invalid_key_gives_friendly_error():
    gm, _ = make_gm(errors.APIError(401, {}))
    with pytest.raises(GameMasterError, match="GEMINI_API_KEY"):
        gm.respond(HISTORY)


def test_retired_model_falls_back_to_next_model():
    # First model returns 404 (retired), the next one works.
    gm, models = make_gm(errors.APIError(404, {}), "Hello from the fallback model")
    gm.model_name = gm.candidate_models[0] = "gemini-2.5-flash"
    assert gm.respond(HISTORY) == "Hello from the fallback model"
    assert gm.model_name != "gemini-2.5-flash"  # remembered for next turns


def test_all_models_missing_gives_helpful_error():
    gm, _ = make_gm(*[errors.APIError(404, {})] * 10)
    with pytest.raises(GameMasterError, match="list_models.py"):
        gm.respond(HISTORY)


def test_timeout_everywhere_gives_friendly_error():
    # Use whichever timeout exception the installed SDK actually raises.
    exc = game_master.TIMEOUT_EXCEPTIONS[-1]("request too slow")
    gm, models = make_gm(*[exc] * 20)
    with pytest.raises(GameMasterError, match="too long"):
        gm.respond(HISTORY)
    # 1 attempt per model (no same-model retry after a timeout), max 3 models
    assert len(models.calls) == game_master.MAX_MODELS_PER_TURN


def test_overloaded_model_503_switches_to_another_model(monkeypatch):
    monkeypatch.setattr(game_master.time, "sleep", lambda s: None)
    gm, models = make_gm(errors.APIError(503, {}), errors.APIError(503, {}), "Reply from backup model")
    first_model = gm.model_name
    assert gm.respond(HISTORY) == "Reply from backup model"
    assert gm.model_name != first_model
    assert len(models.calls) == 3  # 2 tries on busy model + 1 on the next
