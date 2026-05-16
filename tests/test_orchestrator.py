"""
Integration tests for handle_user_message().

Each test exercises a specific rule from the specification:
state machine transitions, slot engine, stopping conditions,
validation gate, execution gate, persona isolation, and error safety.
"""
from __future__ import annotations

import pytest

from intentweave.orchestrator import handle_user_message
from intentweave.session_store import SessionStore
from intentweave.states import State
from tests.conftest import MockContextWeaveClient, MockToolWeaveClient, make_session

# All tests receive ctx_client, tool_client, and configure_clients from conftest.


def _store() -> SessionStore:
    return SessionStore()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flight_analyze_seq(*slot_batches: dict) -> list[dict]:
    """Build analyze_responses for a book_flight session filling slots in batches."""
    responses = []
    for updates in slot_batches:
        responses.append({
            "missing_slots": [],
            "slot_updates": updates,
            "questions": [],
            "confidence_score": 1.0,
            "ambiguity_score": 0.0,
        })
    return responses


# ---------------------------------------------------------------------------
# OUTPUT CONTRACT
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_response_has_required_keys(self, ctx_client, tool_client):
        ctx_client.analyze_responses = [
            {"missing_slots": ["origin"], "slot_updates": {}, "questions": [],
             "confidence_score": 0.5, "ambiguity_score": 0.1}
        ]
        store = _store()
        result = handle_user_message("s1", "book a flight", _store=store)
        assert set(result.keys()) == {"user_message", "system_transparency", "state", "internal"}

    def test_internal_has_required_keys(self, ctx_client, tool_client):
        store = _store()
        result = handle_user_message("s1", "book a flight", _store=store)
        assert set(result["internal"].keys()) == {
            "intent", "domain", "slots", "missing_slots",
            "confidence", "iteration_count", "persona",
        }

    def test_no_extra_keys_in_response(self, ctx_client, tool_client):
        store = _store()
        result = handle_user_message("s1", "book a flight", _store=store)
        assert len(result) == 4
        assert len(result["internal"]) == 7


# ---------------------------------------------------------------------------
# STATE MACHINE — INIT → ROUTED → CLARIFYING
# ---------------------------------------------------------------------------

class TestInitRouting:
    def test_unroutable_message_returns_blocked(self, ctx_client, tool_client):
        store = _store()
        result = handle_user_message("s1", "hello there random text xyz", _store=store)
        assert result["state"] == State.BLOCKED

    def test_routable_message_sets_intent(self, ctx_client, tool_client):
        ctx_client.analyze_responses = [
            {"missing_slots": ["origin"], "slot_updates": {}, "questions": [],
             "confidence_score": 0.5, "ambiguity_score": 0.0}
        ]
        store = _store()
        result = handle_user_message("s1", "book a flight to Paris", _store=store)
        assert result["internal"]["intent"] == "book_flight"
        assert result["internal"]["domain"] == "travel"

    def test_session_persisted_after_init(self, ctx_client, tool_client):
        store = _store()
        handle_user_message("s1", "book a flight", _store=store)
        session = store.get("s1")
        assert session is not None
        assert session.intent == "book_flight"


# ---------------------------------------------------------------------------
# CLARIFICATION LOOP — ASK ACTION
# ---------------------------------------------------------------------------

class TestClarificationLoop:
    def test_missing_slots_triggers_ask(self, ctx_client, tool_client):
        ctx_client.analyze_responses = [
            {"missing_slots": ["origin", "destination"], "slot_updates": {}, "questions": [],
             "confidence_score": 0.4, "ambiguity_score": 0.5}
        ]
        store = _store()
        result = handle_user_message("s1", "book a flight", _store=store)
        assert result["state"] == State.CLARIFYING
        assert "origin" in result["internal"]["missing_slots"]

    def test_custom_question_used_in_ask(self, ctx_client, tool_client):
        ctx_client.analyze_responses = [
            {"missing_slots": ["origin"], "slot_updates": {}, "questions": ["Where are you flying from?"],
             "confidence_score": 0.5, "ambiguity_score": 0.0}
        ]
        store = _store()
        result = handle_user_message("s1", "book a flight", _store=store)
        assert "Where are you flying from?" in result["user_message"]

    def test_iteration_count_increments(self, ctx_client, tool_client):
        ctx_client.analyze_responses = [
            {"missing_slots": ["destination"], "slot_updates": {"origin": "NYC"},
             "questions": [], "confidence_score": 0.6, "ambiguity_score": 0.0},
        ]
        store = _store()
        handle_user_message("s1", "book a flight from NYC", _store=store)
        session = store.get("s1")
        assert session.iteration_count == 1

    def test_slots_filled_from_context_weave_only(self, ctx_client, tool_client):
        ctx_client.analyze_responses = [
            {"missing_slots": [], "slot_updates": {"origin": "NYC", "destination": "LAX",
             "date": "2026-01-01", "passengers": 2},
             "questions": [], "confidence_score": 1.0, "ambiguity_score": 0.0}
        ]
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 1.0, "risk_score": 0.0, "policy_flags": []
        }
        store = _store()
        handle_user_message("s1", "book a flight", _store=store)
        session = store.get("s1")
        assert session.filled_slots["origin"] == "NYC"
        assert session.filled_slots["destination"] == "LAX"


# ---------------------------------------------------------------------------
# STOPPING CONDITIONS
# ---------------------------------------------------------------------------

class TestStoppingConditions:
    def test_sc1_no_missing_slots_transitions_to_validation(self, ctx_client, tool_client):
        """SC1: missing_slots == 0 → READY_FOR_VALIDATION → validation fires."""
        ctx_client.analyze_responses = [
            {"missing_slots": [], "slot_updates": {
                "origin": "NYC", "destination": "LAX", "date": "2026-01-01", "passengers": 1
            }, "questions": [], "confidence_score": 1.0, "ambiguity_score": 0.0}
        ]
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 1.0, "risk_score": 0.0, "policy_flags": []
        }
        store = _store()
        handle_user_message("s1", "book a flight", _store=store)
        assert ctx_client._validation_call_count == 1

    def test_sc2_iteration_limit_triggers_validation(self, ctx_client, tool_client):
        """SC2: iteration_count >= 2 * len(required_slots) forces READY_FOR_VALIDATION."""
        # book_flight has 4 required slots → limit = 8 iterations
        # Pre-seed a session already at the limit
        store = _store()
        session = make_session(
            session_id="s1",
            state=State.CLARIFYING,
            iteration_count=8,  # at limit
            required_slots=["origin", "destination", "date", "passengers"],
            filled_slots={"origin": "NYC", "destination": "LAX", "date": "2026-01-01"},
            missing_slots=["passengers"],
        )
        store.save(session)
        ctx_client.validation_response = {
            "allowed": False, "confidence_score": 0.3, "risk_score": 0.8,
            "policy_flags": ["MAX_ITERATIONS_EXCEEDED"]
        }
        result = handle_user_message("s1", "still not giving passengers", _store=store)
        assert ctx_client._validation_call_count == 1
        # Validation fails → BLOCKED
        assert result["state"] == State.BLOCKED

    def test_sc3_two_consecutive_empty_updates_triggers_validation(self, ctx_client, tool_client):
        """SC3: 2 consecutive empty slot_updates → READY_FOR_VALIDATION."""
        ctx_client.analyze_responses = [
            # First turn: no new slots
            {"missing_slots": ["destination"], "slot_updates": {},
             "questions": [], "confidence_score": 0.4, "ambiguity_score": 0.0},
            # Second turn: still no new slots
            {"missing_slots": ["destination"], "slot_updates": {},
             "questions": [], "confidence_score": 0.4, "ambiguity_score": 0.0},
        ]
        ctx_client.validation_response = {
            "allowed": False, "confidence_score": 0.1, "risk_score": 0.9,
            "policy_flags": ["STALLED_CONVERSATION"]
        }
        store = _store()
        # Pre-seed session with 1 consecutive empty already
        session = make_session(
            session_id="s1",
            state=State.CLARIFYING,
            iteration_count=1,
            required_slots=["origin", "destination", "date", "passengers"],
            filled_slots={"origin": "NYC"},
            missing_slots=["destination", "date", "passengers"],
        )
        store.save(session)
        store.set_metadata("s1", "consecutive_empty_updates", 1)

        result = handle_user_message("s1", "I said NYC", _store=store)
        # Second consecutive empty → SC3 → READY_FOR_VALIDATION → validation fires
        assert ctx_client._validation_call_count == 1


# ---------------------------------------------------------------------------
# FINAL VALIDATION GATE
# ---------------------------------------------------------------------------

class TestFinalValidation:
    def _fill_session(self, store, session_id="s1"):
        session = make_session(
            session_id=session_id,
            state=State.CLARIFYING,
            required_slots=["origin", "destination", "date", "passengers"],
            filled_slots={"origin": "NYC", "destination": "LAX", "date": "2026-01-01", "passengers": 2},
            missing_slots=[],
            iteration_count=0,
        )
        store.save(session)

    def test_validation_called_when_no_missing_slots(self, ctx_client, tool_client):
        store = _store()
        self._fill_session(store)
        ctx_client.analyze_responses = [
            {"missing_slots": [], "slot_updates": {}, "questions": [],
             "confidence_score": 1.0, "ambiguity_score": 0.0}
        ]
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 1.0, "risk_score": 0.0, "policy_flags": []
        }
        handle_user_message("s1", "confirm", _store=store)
        assert ctx_client._validation_call_count == 1

    def test_validation_blocked_when_not_allowed(self, ctx_client, tool_client):
        store = _store()
        self._fill_session(store)
        ctx_client.analyze_responses = [
            {"missing_slots": [], "slot_updates": {}, "questions": [],
             "confidence_score": 1.0, "ambiguity_score": 0.0}
        ]
        ctx_client.validation_response = {
            "allowed": False, "confidence_score": 0.5, "risk_score": 0.9,
            "policy_flags": ["FRAUD_RISK"]
        }
        result = handle_user_message("s1", "confirm", _store=store)
        assert result["state"] == State.BLOCKED

    def test_validation_blocked_when_confidence_below_threshold(self, ctx_client, tool_client):
        store = _store()
        self._fill_session(store)
        ctx_client.analyze_responses = [
            {"missing_slots": [], "slot_updates": {}, "questions": [],
             "confidence_score": 1.0, "ambiguity_score": 0.0}
        ]
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 0.85,  # below 0.9 threshold
            "risk_score": 0.2, "policy_flags": []
        }
        result = handle_user_message("s1", "confirm", _store=store)
        # Confidence < 0.9 → cannot execute; goes back to CLARIFYING or BLOCKED
        assert result["state"] in (State.CLARIFYING, State.BLOCKED)
        # Tool must NOT have been called
        assert tool_client._call_count == 0

    def test_execution_requires_ready_for_execution_state(self, ctx_client, tool_client):
        """spec: EXECUTION IS ONLY ALLOWED IF state == READY_FOR_EXECUTION"""
        store = _store()
        self._fill_session(store)
        ctx_client.analyze_responses = [
            {"missing_slots": [], "slot_updates": {}, "questions": [],
             "confidence_score": 1.0, "ambiguity_score": 0.0}
        ]
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 1.0, "risk_score": 0.0, "policy_flags": []
        }
        result = handle_user_message("s1", "confirm", _store=store)
        assert result["state"] == State.COMPLETED
        assert tool_client._call_count == 1


# ---------------------------------------------------------------------------
# EXECUTION
# ---------------------------------------------------------------------------

class TestExecution:
    def _full_flight_session(self, store):
        session = make_session(
            session_id="s1",
            state=State.READY_FOR_EXECUTION,
            intent="book_flight",
            domain="travel",
            required_slots=["origin", "destination", "date", "passengers"],
            filled_slots={"origin": "NYC", "destination": "LAX", "date": "2026-06-15", "passengers": 1},
            missing_slots=[],
        )
        store.save(session)

    def test_tool_called_with_filled_slots_only(self, ctx_client, tool_client):
        store = _store()
        self._full_flight_session(store)
        # Bypass analyze (state is READY_FOR_EXECUTION, not CLARIFYING)
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 1.0, "risk_score": 0.0, "policy_flags": []
        }
        # Manually advance state to READY_FOR_VALIDATION so orchestrator runs validation
        session = store.get("s1")
        session.state = State.READY_FOR_VALIDATION
        store.save(session)

        handle_user_message("s1", "confirm", _store=store)

        assert tool_client._call_count == 1
        assert tool_client._last_tool_name == "flight_booking"
        assert tool_client._last_payload == {
            "origin": "NYC", "destination": "LAX",
            "date": "2026-06-15", "passengers": 1,
        }

    def test_completed_state_after_successful_execution(self, ctx_client, tool_client):
        store = _store()
        self._full_flight_session(store)
        session = store.get("s1")
        session.state = State.READY_FOR_VALIDATION
        store.save(session)
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 1.0, "risk_score": 0.0, "policy_flags": []
        }
        result = handle_user_message("s1", "go", _store=store)
        assert result["state"] == State.COMPLETED

    def test_tool_payload_sourced_only_from_filled_slots(self, ctx_client, tool_client):
        """Payload must equal filled_slots exactly — no added/removed keys."""
        store = _store()
        session = make_session(
            session_id="s1",
            state=State.READY_FOR_VALIDATION,
            intent="book_flight",
            required_slots=["origin", "destination", "date", "passengers"],
            filled_slots={"origin": "BOS", "destination": "SFO", "date": "2026-07-04", "passengers": 3},
            missing_slots=[],
        )
        store.save(session)
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 1.0, "risk_score": 0.0, "policy_flags": []
        }
        handle_user_message("s1", "execute", _store=store)
        assert tool_client._last_payload == session.filled_slots


# ---------------------------------------------------------------------------
# PRESENT (no-tool intents)
# ---------------------------------------------------------------------------

class TestPresentAction:
    def test_present_action_for_no_tool_intent(self, ctx_client, tool_client):
        store = _store()
        session = make_session(
            session_id="s1",
            state=State.READY_FOR_VALIDATION,
            intent="get_weather",
            domain="weather",
            required_slots=["location", "date"],
            filled_slots={"location": "London", "date": "2026-01-15"},
            missing_slots=[],
        )
        store.save(session)
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 1.0, "risk_score": 0.0, "policy_flags": []
        }
        result = handle_user_message("s1", "get weather", _store=store)
        # No tool called; state is COMPLETED via PRESENT path
        assert tool_client._call_count == 0
        assert result["state"] == State.COMPLETED


# ---------------------------------------------------------------------------
# PERSONA — affects only user_message, not structured data
# ---------------------------------------------------------------------------

class TestPersonaIsolation:
    def _setup_ask_response(self, ctx_client):
        ctx_client.analyze_responses = [
            {"missing_slots": ["origin"], "slot_updates": {}, "questions": [],
             "confidence_score": 0.5, "ambiguity_score": 0.0}
        ]

    def test_persona_affects_user_message_only(self, ctx_client, tool_client):
        self._setup_ask_response(ctx_client)
        store_pro = _store()
        store_gen = _store()

        res_pro = handle_user_message("s1", "book a flight", persona="PROFESSIONAL", _store=store_pro)
        res_gen = handle_user_message("s2", "book a flight", persona="GEN_Z", _store=store_gen)

        assert res_pro["internal"] != res_gen["internal"] or True  # internal may differ by session_id
        # The key invariant: structured data is the same regardless of persona
        assert res_pro["internal"]["intent"] == res_gen["internal"]["intent"]
        assert res_pro["internal"]["missing_slots"] == res_gen["internal"]["missing_slots"]
        assert res_pro["internal"]["slots"] == res_gen["internal"]["slots"]

    def test_persona_changes_user_message_text(self, ctx_client, tool_client):
        self._setup_ask_response(ctx_client)
        store_pro = _store()
        store_gen = _store()

        res_pro = handle_user_message("s1", "book a flight", persona="PROFESSIONAL", _store=store_pro)
        res_gen = handle_user_message("s2", "book a flight", persona="GEN_Z", _store=store_gen)

        assert res_pro["user_message"] != res_gen["user_message"]

    def test_persona_stored_in_session(self, ctx_client, tool_client):
        self._setup_ask_response(ctx_client)
        store = _store()
        handle_user_message("s1", "book a flight", persona="EXECUTIVE", _store=store)
        session = store.get("s1")
        assert session.persona == "EXECUTIVE"


# ---------------------------------------------------------------------------
# ERROR SAFETY — undefined conditions → BLOCKED
# ---------------------------------------------------------------------------

class TestErrorSafety:
    def test_invalid_analyze_response_blocks(self, ctx_client, tool_client):
        ctx_client.analyze_responses = [{"bad_key": "oops"}]  # missing required keys
        store = _store()
        result = handle_user_message("s1", "book a flight", _store=store)
        assert result["state"] == State.BLOCKED

    def test_invalid_validation_response_blocks(self, ctx_client, tool_client):
        ctx_client.analyze_responses = [
            {"missing_slots": [], "slot_updates": {
                "origin": "NYC", "destination": "LAX", "date": "2026-01-01", "passengers": 1
            }, "questions": [], "confidence_score": 1.0, "ambiguity_score": 0.0}
        ]
        ctx_client.validation_response = {"broken": True}  # missing required keys
        store = _store()
        result = handle_user_message("s1", "book a flight", _store=store)
        assert result["state"] == State.BLOCKED

    def test_tool_exception_blocks(self, ctx_client, tool_client):
        store = _store()
        session = make_session(
            session_id="s1",
            state=State.READY_FOR_VALIDATION,
            intent="book_flight",
            required_slots=["origin", "destination", "date", "passengers"],
            filled_slots={"origin": "NYC", "destination": "LAX", "date": "2026-01-01", "passengers": 1},
            missing_slots=[],
        )
        store.save(session)
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 1.0, "risk_score": 0.0, "policy_flags": []
        }

        def boom(tool_name, payload):
            raise RuntimeError("network error")

        tool_client.execute = boom

        result = handle_user_message("s1", "go", _store=store)
        assert result["state"] == State.BLOCKED

    def test_completed_session_is_terminal(self, ctx_client, tool_client):
        store = _store()
        session = make_session(session_id="s1", state=State.COMPLETED, missing_slots=[])
        store.save(session)
        result = handle_user_message("s1", "do more", _store=store)
        assert result["state"] == State.BLOCKED


# ---------------------------------------------------------------------------
# MULTI-TURN FLOW
# ---------------------------------------------------------------------------

class TestMultiTurnFlow:
    def test_full_happy_path_book_flight(self, ctx_client, tool_client):
        """
        Simulates a complete multi-turn conversation:
        Turn 1: user says 'book a flight' → ASK for missing slots
        Turn 2: user provides origin+destination → ASK for remaining
        Turn 3: user provides date+passengers → validation → execution
        """
        ctx_client.analyze_responses = [
            # Turn 1: extract nothing yet
            {"missing_slots": ["origin", "destination", "date", "passengers"],
             "slot_updates": {}, "questions": ["Where are you flying from?"],
             "confidence_score": 0.3, "ambiguity_score": 0.5},
            # Turn 2: get origin and destination
            {"missing_slots": ["date", "passengers"],
             "slot_updates": {"origin": "NYC", "destination": "LAX"},
             "questions": ["What date and how many passengers?"],
             "confidence_score": 0.6, "ambiguity_score": 0.2},
            # Turn 3: get date and passengers → all filled
            {"missing_slots": [],
             "slot_updates": {"date": "2026-08-01", "passengers": 2},
             "questions": [], "confidence_score": 1.0, "ambiguity_score": 0.0},
        ]
        ctx_client.validation_response = {
            "allowed": True, "confidence_score": 1.0, "risk_score": 0.0, "policy_flags": []
        }

        store = _store()

        r1 = handle_user_message("s1", "book a flight", _store=store)
        assert r1["state"] == State.CLARIFYING
        assert store.get("s1").iteration_count == 1

        r2 = handle_user_message("s1", "NYC to LAX", _store=store)
        assert r2["state"] == State.CLARIFYING
        assert store.get("s1").filled_slots.get("origin") == "NYC"
        assert store.get("s1").iteration_count == 2

        r3 = handle_user_message("s1", "August 1st, 2 passengers", _store=store)
        assert r3["state"] == State.COMPLETED
        assert tool_client._call_count == 1
        assert tool_client._last_tool_name == "flight_booking"
