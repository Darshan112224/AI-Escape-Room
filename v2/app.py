"""
app.py — Streamlit user interface for AI Escape Room, Version 2.

Run from the project root:
    streamlit run v2/app.py

Differences from V1's UI:
  • The sidebar shows the REAL game state (inventory, puzzles, door), read
    directly from GameState, not from what the LLM says.
  • An optional debug panel shows, for every turn, how the message was parsed,
    what the engine decided and whether the output guard intervened.
    That's useful for demos and for explaining the architecture.
  • Without an API key the game still runs ("offline mode": rule-based parser
    + plain engine text), proving the rules don't depend on the LLM.
"""

import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from game import EscapeRoomGame
from llm_client import DEFAULT_MODEL, LLMClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

st.set_page_config(page_title="AI Escape Room · V2", page_icon="🔐", layout="centered")


@st.cache_resource  # build once, reuse across reruns
def get_game(api_key: str | None, model_name: str) -> EscapeRoomGame:
    llm = LLMClient(api_key=api_key, model_name=model_name) if api_key else None
    return EscapeRoomGame(llm)


game = get_game(API_KEY, MODEL_NAME)


def init_game() -> None:
    st.session_state.state = game.new_state()
    st.session_state.messages = [{"role": "assistant", "content": game.opening_scene, "debug": None}]
    st.session_state.celebrated = False


if "state" not in st.session_state:
    init_game()

state = st.session_state.state

# ---------------------------------------------------------------------------
# Handle new input FIRST, so the sidebar below already shows the updated state.
# (st.chat_input is always drawn at the bottom of the page, wherever we call it.)
# ---------------------------------------------------------------------------
if not state.escaped:
    if player_input := st.chat_input("What do you do?"):
        st.session_state.messages.append({"role": "user", "content": player_input, "debug": None})
        with st.spinner("The Game Master is thinking..."):
            outcome = game.play_turn(state, player_input)
        st.session_state.messages.append(
            {"role": "assistant", "content": outcome.reply, "debug": outcome.debug_info()}
        )
        if state.escaped:
            st.rerun()  # re-run immediately so the chat input disappears after winning

# ---------------------------------------------------------------------------
# Sidebar: instructions + live game state
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("📜 How to play")
    st.markdown(
        "Escape **The Locked Library**. One action per message, for example:\n"
        "- *examine the desk* · *read the note*\n"
        "- *look behind the painting* · *take the key*\n"
        "- *use the key on the drawer* · *enter 1234*\n"
        "- *inventory* · *hint* · *help*"
    )
    st.divider()

    st.subheader("🎒 Inventory")
    if state.inventory:
        for item in state.inventory:
            st.markdown(f"- {game.engine.name(item)}")
    else:
        st.caption("Empty")

    st.subheader("🧩 Puzzles")
    solved = state.solved_puzzles(game.data)
    for puzzle in game.data["puzzles"]:
        st.markdown(f"{'✅' if puzzle['id'] in solved else '⬜'} {puzzle['title']}")

    st.subheader("🚪 Exit door")
    st.markdown("🔓 **Open**" if state.escaped else "🔒 Locked")

    col1, col2 = st.columns(2)  # side-by-side layout
    col1.metric("Turns", state.turns)
    col2.metric("Wrong codes", state.wrong_attempts)

    st.divider()
    show_debug = st.toggle("🔍 Show engine decisions", value=False)
    if st.button("🔄 Restart game", use_container_width=True):
        init_game()
        st.rerun()

    if game.llm:
        st.caption(f"Version 2 · Model: `{game.llm.model_name}` · LLM calls: {game.llm.calls_made}")
    else:
        st.caption("Version 2 · Offline mode (no API key)")

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("🔐 AI Escape Room")
st.caption("Version 2: Python enforces the rules, the AI tells the story")

if game.llm is None:
    st.warning(
        "No `GEMINI_API_KEY` found, so the game is running in **offline mode**: "
        "simple commands work, and replies are plain text. Add your key to `.env` for the AI narrator."
    )

for msg in st.session_state.messages:
    avatar = "🧙" if msg["role"] == "assistant" else "🧑"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])
        if show_debug and msg.get("debug"):
            # st.expander = collapsible box; st.code shows pretty JSON
            with st.expander("Behind the scenes"):
                st.code(json.dumps(msg["debug"], indent=2), language="json")

if show_debug:
    with st.expander("📦 Full GameState (JSON)"):
        st.code(json.dumps(state.to_dict(), indent=2), language="json")

if state.escaped:
    if not st.session_state.celebrated:
        st.balloons()
        st.session_state.celebrated = True
    st.success(
        f"🎉 **You escaped The Locked Library in {state.turns} turns** "
        f"with {state.wrong_attempts} wrong code(s)! Click *Restart game* to play again."
    )
