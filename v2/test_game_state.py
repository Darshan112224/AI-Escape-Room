"""Tests for the structured game state and the game data file."""

import json

from game_state import GameState, load_game_data

DATA = load_game_data()


def test_game_data_meets_assignment_minimums():
    assert len(DATA["objects"]) >= 5            # at least five interactive objects
    assert len(DATA["puzzles"]) >= 4            # three puzzles + final escape challenge
    assert len(DATA["door"]["solution_code"]) == DATA["door"]["code_length"]


def test_new_state_only_shows_visible_objects():
    state = GameState.new(DATA)
    assert "painting" in state.visible
    assert "brass_key" not in state.visible     # hidden behind the painting
    assert "diary_page" not in state.visible    # hidden in the drawer
    assert state.inventory == [] and not state.escaped


def test_each_state_has_its_own_collections():
    a, b = GameState.new(DATA), GameState.new(DATA)
    a.add_to_inventory("note")
    assert b.inventory == []                    # no shared mutable default


def test_solved_puzzles_are_derived_from_flags():
    state = GameState.new(DATA)
    assert state.solved_puzzles(DATA) == []
    state.set_flag("diary_page_read")
    assert "season_code" not in state.solved_puzzles(DATA)   # needs BOTH flags
    state.set_flag("book_digits_found")
    assert "season_code" in state.solved_puzzles(DATA)


def test_state_round_trips_through_json():
    state = GameState.new(DATA)
    state.add_to_inventory("brass_key")
    state.set_flag("painting_moved")
    restored = GameState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert restored == state
