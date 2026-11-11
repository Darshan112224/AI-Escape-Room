"""
End-to-end UI tests for app.py using Streamlit's built-in testing tool.

`AppTest` runs the Streamlit script headlessly (no browser), lets us type into
the chat input / click buttons, and inspect what appears on screen.
The real Gemini client is replaced by a fake that returns scripted replies.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from google import genai
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parent / "app.py")


class FakeClient:
    """Stands in for genai.Client. Replies are taken from a shared script."""

    script: list[str] = []

    def __init__(self, api_key=None, **kwargs):  # **kwargs swallows http_options etc.
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, model, contents, config):
        return SimpleNamespace(text=FakeClient.script.pop(0))


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(genai, "Client", FakeClient)
    at = AppTest.from_file(APP, default_timeout=10)
    at.run()
    return at


def test_opening_scene_shown(app):
    assert "old library" in app.chat_message[0].markdown[0].value
    assert not app.exception


def test_player_message_gets_reply(app):
    FakeClient.script = ["The frame of the painting looks loose."]
    app.chat_input[0].set_value("examine the painting").run()
    texts = [m.markdown[0].value for m in app.chat_message]
    assert texts[-2] == "examine the painting"
    assert "loose" in texts[-1]
    assert app.session_state.turns == 1


def test_escape_ends_game_and_restart_resets(app):
    FakeClient.script = ["The door swings open. Fresh air! [ESCAPED]"]
    app.chat_input[0].set_value("enter 4158 on the keypad").run()
    assert app.session_state.escaped is True
    assert "You escaped" in app.success[0].value
    assert "[ESCAPED]" not in app.session_state.messages[-1]["content"]
    assert len(app.chat_input) == 0  # input disabled after winning

    app.button[0].click().run()  # Restart
    assert app.session_state.escaped is False
    assert len(app.session_state.messages) == 1
