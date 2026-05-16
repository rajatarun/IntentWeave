"""Shared fixtures for the IntentWeave test suite."""
from __future__ import annotations

import pytest

from intentweave.clients import ContextWeaveClient, ToolWeaveClient
from intentweave.models import Session
from intentweave.session_store import SessionStore
from intentweave.states import State
import intentweave.orchestrator as orch


# ---------------------------------------------------------------------------
# Mock ContextWeaveClient
# ---------------------------------------------------------------------------

class MockContextWeaveClient(ContextWeaveClient):
    """
    Fully configurable mock.  Tests set .analyze_responses and
    .validation_response to control what the mock returns.
    """

    def __init__(self) -> None:
        # List of dicts returned by analyze() in FIFO order.
        # After the list is exhausted, the last entry is repeated.
        self.analyze_responses: list[dict] = [
            {
                "missing_slots": [],
                "slot_updates": {},
                "questions": [],
                "confidence_score": 1.0,
                "ambiguity_score": 0.0,
            }
        ]
        self.validation_response: dict = {
            "allowed": True,
            "confidence_score": 1.0,
            "risk_score": 0.0,
            "policy_flags": [],
        }
        self._analyze_call_count = 0
        self._validation_call_count = 0

    def analyze(self, session: Session, user_message: str) -> dict:
        self._analyze_call_count += 1
        idx = min(self._analyze_call_count - 1, len(self.analyze_responses) - 1)
        return dict(self.analyze_responses[idx])

    def final_validation(self, session: Session) -> dict:
        self._validation_call_count += 1
        return dict(self.validation_response)


# ---------------------------------------------------------------------------
# Mock ToolWeaveClient
# ---------------------------------------------------------------------------

class MockToolWeaveClient(ToolWeaveClient):
    def __init__(self) -> None:
        self.result: dict = {"status": "ok", "confirmation_id": "MOCK-001"}
        self._call_count = 0
        self._last_tool_name: str | None = None
        self._last_payload: dict | None = None

    def execute(self, tool_name: str, payload: dict) -> dict:
        self._call_count += 1
        self._last_tool_name = tool_name
        self._last_payload = dict(payload)
        return dict(self.result)


# ---------------------------------------------------------------------------
# Session factory helpers
# ---------------------------------------------------------------------------

def make_session(
    session_id: str = "test-session",
    user_id: str = "user-1",
    state: str = State.CLARIFYING,
    intent: str | None = "book_flight",
    domain: str | None = "travel",
    required_slots: list[str] | None = None,
    filled_slots: dict | None = None,
    missing_slots: list[str] | None = None,
    iteration_count: int = 0,
    persona: str = "PROFESSIONAL",
) -> Session:
    rs = required_slots if required_slots is not None else ["origin", "destination", "date", "passengers"]
    fs = filled_slots if filled_slots is not None else {}
    ms = missing_slots if missing_slots is not None else list(rs)
    return Session(
        session_id=session_id,
        user_id=user_id,
        intent=intent,
        domain=domain,
        state=state,
        iteration_count=iteration_count,
        required_slots=rs,
        filled_slots=fs,
        missing_slots=ms,
        persona=persona,
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx_client():
    return MockContextWeaveClient()


@pytest.fixture
def tool_client():
    return MockToolWeaveClient()


@pytest.fixture
def session_store():
    s = SessionStore()
    return s


@pytest.fixture(autouse=True)
def configure_clients(ctx_client, tool_client):
    """Wire mock clients into the orchestrator for every test."""
    orch.configure(ctx_client, tool_client)
    yield
    # Reset module-level clients after each test
    orch._context_weave = None
    orch._tool_weave = None
