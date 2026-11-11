"""Headless UI tests for the V2 Streamlit app (Streamlit AppTest)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from google import genai
from streamlit.testing.v1 import AppTest

import llm_client
from intent import Intent

APP = str(Path(__file__).parent / "app.py")


class FakeClient:
    """Stands in for genai.Client: narrator echoes facts, parser says 'unknown'."""

    def __init__(self, *args, **kwargs):
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, model, contents, config):
        if config.response_schema is not None:
            return SimpleNamespace(parsed=Intent(action="unknown"), text=None)
        return SimpleNamespace(text=" ".join(json.loads(contents)["facts"]))


def make_app(monkeypatch, api_key):
    st.cache_resource.clear()               # don't reuse a game from another test
    if api_key:
        monkeypatch.setenv("GEMINI_API_KEY", api_key)
    else:
        monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(llm_client.genai, "Client", FakeClient)
    at = AppTest.from_file(APP, default_timeout=10)
    at.run()
    return at


def say(at, text):
    at.chat_input[0].set_value(text).run()
    return at


@pytest.mark.parametrize("key", ["fake-key", None])
def test_opening_and_sidebar_state(monkeypatch, key):
    at = make_app(monkeypatch, key)
    assert not at.exception
    assert "old library" in at.chat_message[0].markdown[0].value
    assert (len(at.warning) == 1) == (key is None)   # offline banner only without key


def test_inventory_updates_from_real_state(monkeypatch):
    at = make_app(monkeypatch, "fake-key")
    say(at, "look behind the painting")
    say(at, "take the key")
    assert at.session_state.state.inventory == ["brass_key"]
    assert any("brass key" in md.value for md in at.sidebar.markdown)


def test_cheating_code_does_not_win_but_real_solution_does(monkeypatch):
    at = make_app(monkeypatch, None)
    say(at, "4158")
    assert not at.session_state.state.escaped and len(at.success) == 0
    for step in ["read note", "move painting", "take key", "use key on drawer",
                 "read diary page", "examine bookshelf", "examine books", "4158"]:
        say(at, step)
    assert at.session_state.state.escaped
    assert "You escaped" in at.success[0].value
    assert len(at.chat_input) == 0                     # input disabled after winning


def test_restart_resets_state(monkeypatch):
    at = make_app(monkeypatch, None)
    say(at, "move painting")
    at.button[0].click().run()
    assert at.session_state.state.turns == 0 and len(at.session_state.messages) == 1
