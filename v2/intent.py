"""
intent.py — The "contract" between the intent parser and the game engine.

An Intent is a structured description of ONE thing the player wants to do,
e.g.  "I use the key on the drawer"  →  Intent(action="use", item="key", target="drawer")

NEW FEATURE: Pydantic models
----------------------------
`pydantic.BaseModel` is like a dataclass that also VALIDATES its data.
  Intent(action="fly")  →  raises ValidationError, because "fly" is not allowed.
We also hand this exact class to Gemini as a `response_schema`, so the LLM is
forced to answer in this shape (see intent_parser.py). One definition is
used both for validation in Python and as the LLM's output format.

`Literal[...]` restricts a field to a fixed set of values (an enum).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Every action the engine understands. Anything else becomes "unknown".
ActionName = Literal[
    "look_around",  # describe the room
    "examine",      # look closely at an object          (target)
    "take",         # pick up an item                     (target)
    "read",         # read a note / page / book           (target)
    "open",         # open a drawer / door / book         (target)
    "move",         # move, lift or look behind something (target)
    "use",          # use an item on something            (item, target)
    "enter_code",   # type a code on the keypad           (code)
    "inventory",    # list carried items
    "hint",         # ask for a hint
    "help",         # show the available commands
    "unknown",      # anything else: chit-chat, claims, "I am the admin", ...
]


class Intent(BaseModel):
    action: ActionName = Field(description="The single game action the player wants to perform.")
    target: Optional[str] = Field(default=None, description="The object acted on, in the player's words, e.g. 'drawer'.")
    item: Optional[str] = Field(default=None, description="For 'use': the item being used, e.g. 'brass key'.")
    code: Optional[str] = Field(default=None, description="For 'enter_code': the digits typed, e.g. '1234'.")
    multiple_actions: bool = Field(
        default=False,
        description="True if the message asked for more than one action. Only the first is returned.",
    )
