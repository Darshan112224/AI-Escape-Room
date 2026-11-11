"""
llm_client.py — Reusable, robust Gemini wrapper for Version 2.

In V1 this logic lived inside GameMaster. In V2 two components need an LLM
(the intent parser and the narrator), so the error handling learnt in V1 is
moved here and shared:

  • 30 s request timeout          (V1 bug: endless spinner)
  • retry with exponential backoff on 429 / 500 / 503
  • automatic switch to another model when one is busy, retired (404)
    or not on the free tier  (V1 bugs: retired gemini-2.5-flash, 503 overload)
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import Any

from google import genai
from google.genai import errors, types

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("llm_client")

REQUEST_TIMEOUT_SECONDS = 30
MAX_MODELS_PER_CALL = 3
DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",  # Flash-Lite first: ~500 free requests/day vs ~20 for Flash
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-flash-latest",
]


def _timeout_exceptions() -> tuple[type[BaseException], ...]:
    """Older SDK versions use `httpx`, newer ones `httpx2`; support both."""
    found: list[type[BaseException]] = [TimeoutError]
    for lib in ("httpx", "httpx2"):
        try:
            found.append(importlib.import_module(lib).TimeoutException)
        except (ImportError, AttributeError):
            pass
    return tuple(found)


TIMEOUT_EXCEPTIONS = _timeout_exceptions()


class LLMError(Exception):
    """Raised with a user-friendly message when no model could answer."""


class LLMClient:
    def __init__(self, api_key: str, model_name: str = DEFAULT_MODEL, client: Any = None):
        self.client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_SECONDS * 1000),
        )
        self.candidate_models = [model_name] + [m for m in FALLBACK_MODELS if m != model_name]
        self.model_name = model_name
        self.calls_made = 0  # handy for showing quota usage in the UI

    def generate(
        self,
        contents: Any,
        system_instruction: str,
        temperature: float = 0.7,
        response_schema: Any = None,
        max_retries: int = 2,
    ):
        """
        Call Gemini and return the raw response (use `.text` or `.parsed`).

        If `response_schema` is given (a Pydantic class), Gemini's STRUCTURED
        OUTPUT mode is switched on: the model must return JSON matching the
        schema, and the SDK parses it into `response.parsed` for us.
        """
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            response_mime_type="application/json" if response_schema else None,
            response_schema=response_schema,
        )
        models_tried, attempt, last_problem = 1, 0, ""

        while True:
            attempt += 1
            log.info("Asking %s (attempt %d)...", self.model_name, attempt)
            started = time.perf_counter()
            try:
                response = self.client.models.generate_content(
                    model=self.model_name, contents=contents, config=config
                )
                self.calls_made += 1
                log.info("Reply received in %.1fs", time.perf_counter() - started)
                return response

            except TIMEOUT_EXCEPTIONS:
                log.warning("Timed out after %ds", REQUEST_TIMEOUT_SECONDS)
                code, last_problem = "timeout", "Gemini is taking too long to answer."

            except errors.APIError as e:
                log.warning("Gemini error %s: %s", e.code, str(e)[:200])
                code = e.code
                if e.code == 404 or (e.code == 429 and "limit: 0" in str(e)):
                    if self._drop_current_model():
                        attempt = 0
                        continue
                    raise LLMError("No configured Gemini model works for this API key.") from e
                if e.code in (400, 401, 403):
                    raise LLMError("Gemini rejected the request. Check GEMINI_API_KEY in .env.") from e
                if e.code == 429:
                    last_problem = "Free-tier rate limit reached."
                elif e.code in (500, 503):
                    last_problem = "Gemini's servers are overloaded."
                else:
                    raise LLMError(f"Gemini API error ({e.code}).") from e

            # Temporary problem → retry same model, then rotate to another model.
            if attempt < max_retries and code != "timeout":
                time.sleep(2 ** attempt)
                continue
            if models_tried < min(len(self.candidate_models), MAX_MODELS_PER_CALL):
                self._rotate_model()
                models_tried += 1
                attempt = 0
                log.info("Switching to %s", self.model_name)
                continue
            raise LLMError(last_problem)

    def _drop_current_model(self) -> bool:
        idx = self.candidate_models.index(self.model_name)
        self.candidate_models.pop(idx)
        if not self.candidate_models:
            return False
        self.model_name = self.candidate_models[idx % len(self.candidate_models)]
        return True

    def _rotate_model(self) -> None:
        idx = self.candidate_models.index(self.model_name)
        self.model_name = self.candidate_models[(idx + 1) % len(self.candidate_models)]
