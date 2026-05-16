"""Tests for the State class — exact nine states, no more."""
from __future__ import annotations

import pytest

from intentweave.states import State


EXPECTED_STATES = {
    "INIT", "ROUTED", "CLARIFYING", "STRUCTURING",
    "READY_FOR_VALIDATION", "READY_FOR_EXECUTION",
    "EXECUTING", "COMPLETED", "BLOCKED",
}


def test_all_states_defined():
    for s in EXPECTED_STATES:
        assert hasattr(State, s), f"State.{s} missing"


def test_state_values_are_strings():
    for s in EXPECTED_STATES:
        assert isinstance(getattr(State, s), str)


def test_state_value_matches_name():
    for s in EXPECTED_STATES:
        assert getattr(State, s) == s, f"State.{s} value must equal '{s}'"


def test_is_valid_accepts_all_defined():
    for s in EXPECTED_STATES:
        assert State.is_valid(s), f"State.is_valid should accept '{s}'"


def test_is_valid_rejects_unknown():
    assert not State.is_valid("UNKNOWN")
    assert not State.is_valid("")
    assert not State.is_valid("PENDING")


def test_no_extra_public_states():
    public_attrs = {
        k for k, v in vars(State).items()
        if not k.startswith("_") and isinstance(v, str)
    }
    assert public_attrs == EXPECTED_STATES, (
        f"Extra or missing state attrs: {public_attrs.symmetric_difference(EXPECTED_STATES)}"
    )
