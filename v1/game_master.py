"""
game_master.py — Talks to the Gemini API.

Responsibilities:
  1. Convert our chat history into the format Gemini expects.
  2. Send it together with the system prompt and return the Game Master's reply.
  3. Retry on temporary errors (rate limit / server busy).
  4. Detect the [ESCAPED] marker that signals the player has won.

HOW "MEMORY" WORKS IN VERSION 1
-------------------------------
An LLM API is *stateless*: it remembers nothing between calls. To make the Game
Master "remember" what happened, we resend the WHOLE conversation on every turn.
So the conversation itself is the only game state in V1. If the model misreads
or ignores part of that history, the game state is effectively corrupted.
That is one of the main problems Version 2 solves.
"""

from __future__ import annotations

import time

from google import genai
from google.genai import errors, types

from prompts import ESCAPE_MARKER, GAME_MASTER_PROMPT

# HTTP status codes that are usually temporary and worth retrying:
# 429 = too many requests (free-tier rate limit), 500/503 = server busy.
RETRYABLE_CODES = {429, 500, 503}

# Google retires model names every few months (e.g. gemini-2.5-flash -> 404).
# If the configured model is gone, we automatically try these in order.
FALLBACK_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-flash-latest",  # alias that always points to the newest Flash
]


class GameMasterError(Exception):
    """Raised with a user-friendly message when the LLM call fails."""


class GameMaster:
    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-3.5-flash",
        temperature: float = 0.8,
        client: genai.Client | None = None,
    ):
        # Dependency injection: tests can pass a fake `client`, so we can test
        # the logic without a real API key or network access.
        self.client = client or genai.Client(api_key=api_key)
        # Models to try, in order: the one from .env first, then the fallbacks.
        self.candidate_models = [model_name] + [m for m in FALLBACK_MODELS if m != model_name]
        self.model_name = model_name  # the model currently in use
        # GenerateContentConfig bundles the settings sent with every request.
        # temperature: 0 = predictable, higher = more creative. 0.8 gives lively
        # descriptions (and, as we will see, also more chance of rule-bending).
        self.config = types.GenerateContentConfig(
            system_instruction=GAME_MASTER_PROMPT,
            temperature=temperature,
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_gemini_contents(history: list[dict]) -> list[types.Content]:
        """
        Our history format:   [{"role": "user" | "assistant", "content": "..."}]
        Gemini's format:      Content(role="user" | "model", parts=[Part(text=...)])
        """
        contents: list[types.Content] = []

        # Gemini expects the conversation to start with a user turn, but our
        # game starts with the Game Master's opening scene. So we add a tiny
        # invisible "start" message from the user first.
        if history and history[0]["role"] == "assistant":
            contents.append(
                types.Content(role="user", parts=[types.Part.from_text(text="Start the game.")])
            )

        for msg in history:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append(
                types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])])
            )
        return contents

    # ------------------------------------------------------------------ #
    def respond(self, history: list[dict], max_retries: int = 3) -> str:
        """Send the full conversation to Gemini and return the Game Master's reply."""
        contents = self._to_gemini_contents(history)
        attempt = 0

        while True:
            attempt += 1
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=self.config,
                )
                text = (response.text or "").strip()
                if not text:
                    # Can happen if the response was blocked by a safety filter.
                    return "The Game Master stays silent for a moment... (try rephrasing your action)"
                return text

            except errors.APIError as e:
                # Model is gone (404), or not on the free tier ("limit: 0" quota)
                # → switch to the next candidate model and try again right away.
                not_free = e.code == 429 and "limit: 0" in str(e)
                if e.code == 404 or not_free:
                    if self._switch_to_next_model():
                        attempt = 0
                        continue
                    raise GameMasterError(
                        f"None of the models {self.candidate_models} worked for your key. "
                        "Run `python v1/list_models.py` to see which models you can use, "
                        "then set GEMINI_MODEL in .env."
                    ) from e

                if e.code in RETRYABLE_CODES and attempt < max_retries:
                    # Exponential backoff: wait 2s, 4s, 8s ... before retrying.
                    time.sleep(2 ** attempt)
                    continue
                if e.code == 429:
                    raise GameMasterError(
                        "Rate limit reached on the free Gemini tier. Wait a minute and try again."
                    ) from e
                if e.code in (400, 401, 403):
                    raise GameMasterError(
                        "Gemini rejected the request. Check that GEMINI_API_KEY in your .env is valid."
                    ) from e
                raise GameMasterError(f"Gemini API error ({e.code}). Please try again.") from e

    def _switch_to_next_model(self) -> bool:
        """Move to the next candidate model. Returns False if none are left."""
        idx = self.candidate_models.index(self.model_name)
        if idx + 1 >= len(self.candidate_models):
            return False
        self.model_name = self.candidate_models[idx + 1]
        return True

    # ------------------------------------------------------------------ #
    @staticmethod
    def check_escape(reply: str) -> tuple[bool, str]:
        """
        Returns (escaped, reply_without_marker).

        In V1 the LLM itself decides when the player has won and signals it by
        writing [ESCAPED]. Python simply trusts that marker. This is a weak
        point: if the LLM can be persuaded to write the marker, the player
        "wins" without solving anything.
        """
        escaped = ESCAPE_MARKER in reply
        return escaped, reply.replace(ESCAPE_MARKER, "").strip()
