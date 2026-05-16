"""Tests for the Session dataclass schema."""
from __future__ import annotations

import dataclasses

import pytest

from intentweave.models import Session
from intentweave.states import State


REQUIRED_FIELDS = {
    "session_id", "user_id", "intent", "domain", "state",
    "iteration_count", "required_slots", "filled_slots", "missing_slots", "persona",
}


def test_session_has_exactly_required_fields():
    field_names = {f.name for f in dataclasses.fields(Session)}
    assert field_names == REQUIRED_FIELDS, (
        f"Schema mismatch: {field_names.symmetric_difference(REQUIRED_FIELDS)}"
    )


def test_session_instantiation():
    s = Session(
        session_id="s1",
        user_id="u1",
        intent=None,
        domain=None,
        state=State.INIT,
        iteration_count=0,
        required_slots=[],
        filled_slots={},
        missing_slots=[],
        persona="PROFESSIONAL",
    )
    assert s.session_id == "s1"
    assert s.user_id == "u1"
    assert s.intent is None
    assert s.state == State.INIT
    assert s.iteration_count == 0
    assert s.persona == "PROFESSIONAL"


def test_session_fields_are_mutable():
    s = Session(
        session_id="s1", user_id="u1", intent=None, domain=None,
        state=State.INIT, iteration_count=0, required_slots=[],
        filled_slots={}, missing_slots=[], persona="PROFESSIONAL",
    )
    s.state = State.CLARIFYING
    s.intent = "book_flight"
    s.iteration_count = 3
    assert s.state == State.CLARIFYING
    assert s.intent == "book_flight"
    assert s.iteration_count == 3
