"""
app.py — Streamlit user interface for AI Escape Room, Version 1.

Run from the project root:
    streamlit run v1/app.py

HOW STREAMLIT WORKS (important to understand!)
----------------------------------------------
Streamlit re-runs this ENTIRE script from top to bottom every time the user
interacts (sends a message, clicks a button). Normal Python variables are
therefore reset on every interaction.

To keep data between reruns we use `st.session_state`: a dictionary-like
object that survives reruns for as long as the browser tab is open. Our chat
history lives there.
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from game_master import GameMaster, GameMasterError
from prompts import OPENING_SCENE

# --- Configuration ---------------------------------------------------------
# load_dotenv() reads key=value pairs from the .env file into os.environ.
# The .env lives in the project root (one folder above v1/).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

st.set_page_config(page_title="AI Escape Room · V1", page_icon="🔐", layout="centered")


# --- Session state ---------------------------------------------------------
def init_game() -> None:
    """Create a fresh game in session_state."""
    st.session_state.messages = [{"role": "assistant", "content": OPENING_SCENE}]
    st.session_state.escaped = False
    st.session_state.turns = 0


if "messages" not in st.session_state:  # first visit → new game
    init_game()


# --- Sidebar: instructions --------------------------------------------------
with st.sidebar:
    st.header("📜 How to play")
    st.markdown(
        """
You are trapped in **The Locked Library**. Find clues, solve the puzzles
and enter the right code to escape.

Type what you want to do in plain English, for example:
- *examine the desk*
- *look behind the painting*
- *take the key*
- *open the drawer with the key*
- *enter 1234 on the keypad*

Stuck? Ask the Game Master for a **hint**.
        """
    )
    st.divider()
    st.metric("Turns taken", st.session_state.turns)
    # A button returns True only in the rerun right after it was clicked.
    if st.button("🔄 Restart game", use_container_width=True):
        init_game()
        st.rerun()  # immediately re-run the script so the fresh game is shown


# --- Main area ---------------------------------------------------------------
st.title("🔐 AI Escape Room")
st.caption("Version 1: the AI Game Master runs the whole game")

if not API_KEY:
    st.error(
        "No `GEMINI_API_KEY` found. Copy `.env.example` to `.env` in the project "
        "root and paste your free key from https://aistudio.google.com/apikey"
    )
    st.stop()  # halts the script here; nothing below runs


# `@st.cache_resource` creates the GameMaster ONCE and reuses it on every rerun
# (instead of building a new API client each time the script re-runs).
@st.cache_resource
def get_game_master(api_key: str, model_name: str) -> GameMaster:
    return GameMaster(api_key=api_key, model_name=model_name)


game_master = get_game_master(API_KEY, MODEL_NAME)

# Placeholder in the sidebar; filled at the end of the script so it shows the
# model that was ACTUALLY used (it may differ after an automatic fallback).
model_caption = st.sidebar.empty()

# Draw the chat so far. st.chat_message gives the nice chat-bubble layout.
for msg in st.session_state.messages:
    avatar = "🧙" if msg["role"] == "assistant" else "🧑"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

def show_victory() -> None:
    st.balloons()
    st.success(
        f"🎉 **You escaped The Locked Library in {st.session_state.turns} turns!** "
        "Click *Restart game* in the sidebar to play again."
    )


# Game over → show the victory banner and don't accept more input.
if st.session_state.escaped:
    show_victory()
    st.stop()

# `:=` is the "walrus operator" (Python 3.8+): it assigns AND tests in one step.
# st.chat_input returns the typed text, or None if nothing was sent this run.
if player_input := st.chat_input("What do you do?"):
    st.session_state.turns += 1
    st.session_state.messages.append({"role": "user", "content": player_input})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(player_input)

    with st.chat_message("assistant", avatar="🧙"):
        with st.spinner("The Game Master is thinking..."):
            try:
                reply = game_master.respond(st.session_state.messages)
            except GameMasterError as e:
                # Remove the unanswered message so the history stays consistent.
                st.session_state.messages.pop()
                st.session_state.turns -= 1
                st.error(str(e))
                st.stop()
        # The LLM decides whether the player won (V1 weakness, see game_master.py).
        escaped, reply = GameMaster.check_escape(reply)
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})

    if escaped:
        st.session_state.escaped = True
        st.rerun()  # rerun so the victory screen appears and input is disabled

model_caption.caption(f"Version 1 · Model: `{game_master.model_name}`")
