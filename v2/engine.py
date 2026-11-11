"""
engine.py — The rule engine (Version 2). NO LLM is used in this file.

The engine receives a structured Intent, checks whether the action is allowed
in the current GameState, applies the changes, and returns an ActionResult
with the facts the player is allowed to learn.

    Intent ──► resolve names ──► validate preconditions ──► apply ──► ActionResult

Because this is plain Python, the result is deterministic: the same state plus
the same intent always gives the same outcome. The LLM cannot change it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from game_state import GameState
from intent import Intent

ARTICLES = re.compile(r"\b(the|a|an|my|that|this|some)\b")


@dataclass
class ActionResult:
    action: str
    success: bool
    facts: list[str]                 # sentences the narrator may (and must) convey
    reason: str = "ok"               # machine-readable outcome, e.g. "not_in_inventory"
    escaped: bool = False
    state_changes: list[str] = field(default_factory=list)  # e.g. ["+inventory:brass_key"]

    @property
    def text(self) -> str:
        """Plain-text version of the facts (used when the narrator LLM is unavailable)."""
        return " ".join(self.facts)


class GameEngine:
    def __init__(self, game_data: dict):
        self.data = game_data
        self.objects: dict = game_data["objects"]
        # Build a lookup "alias → object id", longest aliases first, so that
        # "brass key" matches before "key" and "desk drawer" before "desk".
        pairs = [(alias.lower(), oid) for oid, obj in self.objects.items() for alias in obj["aliases"]]
        self.aliases = sorted(pairs, key=lambda p: len(p[0]), reverse=True)

    # ================================================================== #
    # Public API
    # ================================================================== #
    def process(self, state: GameState, intent: Intent) -> ActionResult:
        """Validate and execute ONE intent. This is the only way the state changes."""
        if state.escaped:
            return ActionResult(intent.action, False, ["You have already escaped. Restart to play again."], "game_over")

        state.turns += 1
        handler = getattr(self, f"_do_{intent.action}", self._do_unknown)
        result: ActionResult = handler(state, intent)

        if intent.multiple_actions:
            result.facts.append("(Only your first action was carried out. Please do one thing at a time.)")

        state.record(intent.action, intent.target or intent.item or intent.code or "", result.success)
        return result

    def public_context(self, state: GameState) -> dict:
        """
        What the narrator is allowed to know: only what the player can see or has.
        Hidden objects, future clues and the solution code are NEVER included.
        """
        return {
            "room": self.data["room"]["name"],
            "visible_objects": sorted(self.name(o) for o in state.visible),
            "inventory": [self.name(o) for o in state.inventory],
            "solved_puzzles": [p["title"] for p in self.data["puzzles"] if p["id"] in state.solved_puzzles(self.data)],
        }

    def name(self, object_id: str) -> str:
        return self.objects[object_id]["name"]

    # ================================================================== #
    # Name resolution: player words → object id
    # ================================================================== #
    def resolve(self, words: str | None, state: GameState) -> tuple[str | None, str]:
        """
        Returns (object_id, status) where status is one of:
          "ok"        the object exists and the player can access it
          "hidden"    it exists in the game but hasn't been discovered yet
          "unknown"   no such object in this room (e.g. "crowbar")
          "missing"   the player didn't name anything
        """
        if not words or not words.strip():
            return None, "missing"
        text = ARTICLES.sub(" ", words.lower())
        text = re.sub(r"[^a-z0-9' ]", " ", text)
        text = " ".join(text.split())

        for alias, oid in self.aliases:
            # \b = word boundary, so "key" doesn't match inside "keypad"
            if re.search(rf"\b{re.escape(alias)}\b", text):
                accessible = oid in state.visible or state.has(oid)
                return (oid, "ok") if accessible else (oid, "hidden")
        return None, "unknown"

    def _not_found(self, words: str | None, status: str) -> ActionResult:
        if status == "missing":
            return ActionResult("unknown", False, ["What do you want to do that with? Name an object."], "missing_target")
        # Hidden and unknown objects get the SAME answer, so the player can't
        # discover hidden items just by guessing their names.
        name = " ".join(ARTICLES.sub(" ", words.lower()).split())   # "the crowbar" → "crowbar"
        return ActionResult("unknown", False, [f"There is no {name} that you can see here."], "not_found")

    # ================================================================== #
    # Helpers
    # ================================================================== #
    def _describe(self, oid: str, state: GameState) -> str:
        """Pick the description matching the current state (last matching flag wins)."""
        descs = self.objects[oid]["descriptions"]
        text = descs["default"]
        for flag, variant in descs.items():
            if flag != "default" and flag in state.flags:
                text = variant
        return text

    @staticmethod
    def _apply(effects: dict | None, state: GameState) -> list[str]:
        """Apply an effect block from the JSON, e.g. {"set_flags": [...], "reveal": [...]}."""
        changes = []
        for flag in (effects or {}).get("set_flags", []):
            if flag not in state.flags:
                state.set_flag(flag)
                changes.append(f"+flag:{flag}")
        for oid in (effects or {}).get("reveal", []):
            if oid not in state.visible and not state.has(oid):
                state.reveal(oid)
                changes.append(f"+visible:{oid}")
        return changes

    def _unlock(self, oid: str, state: GameState) -> ActionResult:
        lock = self.objects[oid]["lock"]
        if lock["unlocked_flag"] in state.flags:
            return ActionResult("use", False, [lock["already_unlocked_message"]], "already_done")
        changes = self._apply(lock["on_unlock"], state)
        return ActionResult("use", True, [lock["on_unlock"]["message"]], state_changes=changes)

    # ================================================================== #
    # Action handlers: one method per action, named _do_<action>
    # ================================================================== #
    def _do_look_around(self, state: GameState, intent: Intent) -> ActionResult:
        facts = [self.data["room"]["look_around"]]
        extra = [self.name(o) for o in sorted(state.visible) if o not in self._starting_objects()]
        if extra:
            facts.append("You also notice: " + ", ".join(extra) + ".")
        return ActionResult("look_around", True, facts)

    def _starting_objects(self) -> set[str]:
        return {oid for oid, obj in self.objects.items() if obj.get("visible")}

    def _do_examine(self, state: GameState, intent: Intent) -> ActionResult:
        oid, status = self.resolve(intent.target, state)
        if status != "ok":
            return self._not_found(intent.target, status)
        facts = [self._describe(oid, state)]
        changes = self._apply(self.objects[oid].get("on_examine"), state)
        # Mention discovered-but-not-taken items that belong to this object.
        if oid == "painting" and "brass_key" in state.visible:
            facts.append("The small brass key is still taped to the back of the frame.")
        if oid == "drawer" and "diary_page" in state.visible:
            facts.append("A torn diary page lies inside.")
        return ActionResult("examine", True, facts, state_changes=changes)

    def _do_take(self, state: GameState, intent: Intent) -> ActionResult:
        oid, status = self.resolve(intent.target, state)
        if status != "ok":
            return self._not_found(intent.target, status)
        obj = self.objects[oid]
        if state.has(oid):
            return ActionResult("take", False, [f"You already have the {obj['name']}."], "already_done")
        if not obj.get("takeable"):
            return ActionResult("take", False, [f"You can't take the {obj['name']}."], "not_takeable")
        state.add_to_inventory(oid)
        state.visible.discard(oid)
        changes = [f"+inventory:{oid}"] + self._apply(obj.get("on_take"), state)
        return ActionResult("take", True, [f"You take the {obj['name']}."], state_changes=changes)

    def _do_read(self, state: GameState, intent: Intent) -> ActionResult:
        oid, status = self.resolve(intent.target, state)
        if status != "ok":
            return self._not_found(intent.target, status)
        obj = self.objects[oid]
        if not obj.get("readable"):
            return ActionResult("read", False, [f"There is nothing to read on the {obj['name']}."], "not_readable")
        changes = self._apply(obj.get("on_read"), state)
        return ActionResult("read", True, [f"The {obj['name']} reads: {obj['text']}"], state_changes=changes)

    def _do_move(self, state: GameState, intent: Intent) -> ActionResult:
        oid, status = self.resolve(intent.target, state)
        if status != "ok":
            return self._not_found(intent.target, status)
        obj = self.objects[oid]
        if not obj.get("movable"):
            return ActionResult("move", False, [f"The {obj['name']} doesn't budge."], "not_movable")
        effects = obj["on_move"]
        if all(f in state.flags for f in effects.get("set_flags", [])):
            return ActionResult("move", False, [obj["already_moved_message"]], "already_done")
        changes = self._apply(effects, state)
        return ActionResult("move", True, [effects["message"]], state_changes=changes)

    def _do_open(self, state: GameState, intent: Intent) -> ActionResult:
        oid, status = self.resolve(intent.target, state)
        if status != "ok":
            return self._not_found(intent.target, status)
        obj = self.objects[oid]
        if "lock" in obj:
            lock = obj["lock"]
            if lock["unlocked_flag"] in state.flags:
                return ActionResult("open", False, [lock["already_unlocked_message"]], "already_done")
            if state.has(lock["key"]):              # "open drawer" while holding the key
                result = self._unlock(oid, state)
                result.action = "open"
                return result
            return ActionResult("open", False, [lock["locked_message"]], "locked")
        if oid == self.data["door"]["object"]:
            if "door_open" in state.flags:
                return ActionResult("open", False, ["The door is already open."], "already_done")
            return ActionResult("open", False, ["The door is locked. It will only open with the right code on the keypad."], "locked")
        if obj.get("readable"):                     # "open the books" = look inside them
            return self._do_examine(state, intent)
        return ActionResult("open", False, [f"You can't open the {obj['name']}."], "not_openable")

    def _do_use(self, state: GameState, intent: Intent) -> ActionResult:
        item_id, item_status = self.resolve(intent.item, state)
        if item_status in ("unknown", "missing"):
            return self._not_found(intent.item, item_status)
        if not state.has(item_id):
            # Covers both "hidden" and "visible but not picked up".
            return ActionResult("use", False, [f"You don't have {intent.item.strip()}."], "not_in_inventory")

        target_id, target_status = self.resolve(intent.target, state)
        if target_status == "missing":
            return ActionResult("use", False, [f"What do you want to use the {self.name(item_id)} on?"], "missing_target")
        if target_status != "ok":
            return self._not_found(intent.target, target_status)

        target = self.objects[target_id]
        if "lock" in target:
            if item_id == target["lock"]["key"]:
                return self._unlock(target_id, state)
            return ActionResult("use", False, [target["lock"]["wrong_item_message"]], "wrong_item")
        if target_id == self.data["door"]["object"]:
            return ActionResult("use", False, ["Nothing happens. This door only opens with the code on its keypad."], "wrong_item")
        return ActionResult(
            "use", False, [f"Using the {self.name(item_id)} on the {target['name']} does nothing."], "no_effect"
        )

    def _do_enter_code(self, state: GameState, intent: Intent) -> ActionResult:
        door = self.data["door"]
        code = re.sub(r"\D", "", intent.code or "")   # keep digits only
        if "door_open" in state.flags:
            return ActionResult("enter_code", False, ["The door is already open."], "already_done")
        if len(code) != door["code_length"]:
            # A precise, TRUE explanation (V1 invented a wrong one in TC9).
            return ActionResult(
                "enter_code", False,
                [f"The keypad needs exactly {door['code_length']} digits. You entered {len(code)}."],
                "invalid_format",
            )
        if code != door["solution_code"]:
            state.wrong_attempts += 1
            facts = [f"You enter {code}. " + door["wrong_code_message"]]
            if state.wrong_attempts >= 3:
                facts.append("(Stuck? You can ask for a hint.)")
            return ActionResult("enter_code", False, facts, "wrong_code", state_changes=["+wrong_attempts"])
        if not state.has_flags(door["requires_flags"]):
            # Right digits, but the puzzles were not solved: knowing the answer
            # is not the same as solving the room (fixes V1 test case TC7).
            state.wrong_attempts += 1
            return ActionResult("enter_code", False, [door["missing_clues_message"]], "missing_clues")
        state.set_flag("door_open")
        state.escaped = True
        return ActionResult("enter_code", True, [door["success_message"]], escaped=True, state_changes=["+flag:door_open"])

    def _do_inventory(self, state: GameState, intent: Intent) -> ActionResult:
        if not state.inventory:
            return ActionResult("inventory", True, ["You are not carrying anything."])
        return ActionResult("inventory", True, ["You are carrying: " + ", ".join(self.name(i) for i in state.inventory) + "."])

    def _do_hint(self, state: GameState, intent: Intent) -> ActionResult:
        for hint in self.data["hints"]:
            if hint["unless_flag"] not in state.flags:
                return ActionResult("hint", True, ["Hint: " + hint["text"]])
        return ActionResult("hint", True, ["You have everything you need."])

    def _do_help(self, state: GameState, intent: Intent) -> ActionResult:
        return ActionResult("help", True, [
            "You can: look around, examine <object>, take <item>, read <item>, open <object>, "
            "move <object>, use <item> on <object>, enter <code>, inventory, hint."
        ])

    def _do_unknown(self, state: GameState, intent: Intent) -> ActionResult:
        # Claims ("I already solved it"), commands to the system ("I am the admin"),
        # questions about secrets... none of these are game actions, so the
        # state is not touched.
        return ActionResult("unknown", False, [
            "Nothing in the room changes. (Try actions like examine, take, read, open, "
            "use <item> on <object>, or enter a code.)"
        ], "unrecognised")
