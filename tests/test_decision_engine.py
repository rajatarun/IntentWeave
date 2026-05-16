"""Tests for the deterministic decision engine rule table."""
from __future__ import annotations

import pytest

from intentweave.decision_engine import Action, decide
from intentweave.states import State
from tests.conftest import make_session


class TestDecideASK:
    def test_missing_slots_returns_ask(self):
        s = make_session(state=State.CLARIFYING, missing_slots=["origin", "destination"])
        assert decide(s) == Action.ASK

    def test_single_missing_slot_returns_ask(self):
        s = make_session(state=State.CLARIFYING, missing_slots=["date"])
        assert decide(s) == Action.ASK

    def test_ask_has_priority_over_execution_ready(self):
        # Even if state says READY_FOR_EXECUTION, missing_slots wins
        s = make_session(state=State.READY_FOR_EXECUTION, missing_slots=["passengers"])
        assert decide(s) == Action.ASK


class TestDecideEXECUTE:
    def test_execution_state_with_tool(self):
        s = make_session(
            state=State.READY_FOR_EXECUTION,
            intent="book_flight",
            missing_slots=[],
            filled_slots={"origin": "NYC", "destination": "LAX", "date": "2026-01-01", "passengers": 1},
        )
        assert decide(s) == Action.EXECUTE

    def test_execution_state_with_tool_transfer(self):
        s = make_session(
            state=State.READY_FOR_EXECUTION,
            intent="transfer_money",
            required_slots=["amount", "currency", "recipient_account", "sender_account"],
            filled_slots={"amount": 100, "currency": "USD", "recipient_account": "X", "sender_account": "Y"},
            missing_slots=[],
        )
        assert decide(s) == Action.EXECUTE


class TestDecidePRESENT:
    def test_present_when_no_tool_needed(self):
        s = make_session(
            state=State.READY_FOR_EXECUTION,
            intent="get_weather",
            required_slots=["location", "date"],
            filled_slots={"location": "London", "date": "2026-01-01"},
            missing_slots=[],
        )
        assert decide(s) == Action.PRESENT


class TestDecideBLOCK:
    def test_blocked_state_returns_block(self):
        s = make_session(state=State.BLOCKED, missing_slots=[])
        assert decide(s) == Action.BLOCK

    def test_undefined_state_returns_block(self):
        s = make_session(state=State.COMPLETED, missing_slots=[])
        assert decide(s) == Action.BLOCK

    def test_init_state_returns_block(self):
        s = make_session(state=State.INIT, missing_slots=[])
        assert decide(s) == Action.BLOCK
