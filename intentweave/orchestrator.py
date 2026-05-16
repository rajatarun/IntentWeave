"""
IntentWeave Orchestrator — deterministic, state-machine-driven workflow engine.

handle_user_message() is the ONLY public entry point.
All behaviour is governed by the hard rule table in the specification.
"""
from __future__ import annotations

from intentweave.clients import (
    ContextWeaveClient,
    ToolWeaveClient,
    validate_analyze_response,
    validate_final_validation_response,
)
from intentweave.decision_engine import Action, decide
from intentweave.intent_registry import get_intent_config, get_tool_name, route_intent
from intentweave.models import Session
from intentweave.personas import PERSONAS, transform
from intentweave.session_store import SessionStore, store as _default_store
from intentweave.slot_engine import apply_slot_updates, compute_missing_slots
from intentweave.states import State

# ---------------------------------------------------------------------------
# Dependency injection — configure before calling handle_user_message()
# ---------------------------------------------------------------------------

_context_weave: ContextWeaveClient | None = None
_tool_weave: ToolWeaveClient | None = None


def configure(
    context_weave: ContextWeaveClient,
    tool_weave: ToolWeaveClient,
) -> None:
    """Wire in the external API clients. Must be called before first use."""
    global _context_weave, _tool_weave
    _context_weave = context_weave
    _tool_weave = tool_weave


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def _new_session(
    session_id: str,
    user_id: str,
    persona: str,
) -> Session:
    if persona not in PERSONAS:
        persona = "PROFESSIONAL"
    return Session(
        session_id=session_id,
        user_id=user_id,
        intent=None,
        domain=None,
        state=State.INIT,
        iteration_count=0,
        required_slots=[],
        filled_slots={},
        missing_slots=[],
        persona=persona,
    )


# ---------------------------------------------------------------------------
# Response builders (neutral baseline; persona transform applied afterwards)
# ---------------------------------------------------------------------------

def _build_raw_message(
    action: str,
    session: Session,
    questions: list[str],
    tool_result: dict | None,
    validation_result: dict | None,
) -> str:
    if action == Action.ASK:
        slot_list = ", ".join(session.missing_slots)
        if questions:
            return questions[0]
        return f"Please provide the following information: {slot_list}."

    if action == Action.EXECUTE:
        if tool_result is not None:
            return (
                f"Your {session.intent} request has been submitted successfully. "
                f"Result: {tool_result}."
            )
        return f"Your {session.intent} request has been submitted successfully."

    if action == Action.PRESENT:
        data = ", ".join(f"{k}={v}" for k, v in session.filled_slots.items())
        return f"Here is the result for your {session.intent}: {data}."

    if action == Action.BLOCK:
        if validation_result and validation_result.get("policy_flags"):
            flags = ", ".join(validation_result["policy_flags"])
            return f"Your request has been blocked: {flags}."
        return "Your request cannot be processed due to a policy or validation failure."

    # Unreachable under spec — undefined action is already blocked upstream
    return "Your request cannot be processed."


def _build_system_transparency(
    action: str,
    session: Session,
    analysis: dict | None,
    validation_result: dict | None,
) -> str:
    parts = [f"action={action}", f"state={session.state}"]
    if analysis:
        parts.append(f"confidence={analysis.get('confidence_score', 0.0):.2f}")
    if validation_result:
        parts.append(f"allowed={validation_result.get('allowed')}")
        parts.append(f"risk={validation_result.get('risk_score', 0.0):.2f}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Clarification-loop stopping conditions
# ---------------------------------------------------------------------------

_MAX_CONSECUTIVE_EMPTY = 2


def _stopping_condition_met(
    session: Session,
    consecutive_empty: int,
) -> bool:
    """
    Returns True if ANY of the three stopping conditions is satisfied:
    SC1: len(missing_slots) == 0
    SC2: iteration_count >= 2 * len(required_slots)
    SC3: ContextWeave returned no new slot_updates for 2 consecutive iterations
    """
    sc1 = len(session.missing_slots) == 0
    sc2 = session.iteration_count >= 2 * len(session.required_slots)
    sc3 = consecutive_empty >= _MAX_CONSECUTIVE_EMPTY
    return sc1 or sc2 or sc3


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def handle_user_message(
    session_id: str,
    user_message: str,
    *,
    user_id: str = "anonymous",
    persona: str = "PROFESSIONAL",
    _store: SessionStore | None = None,
) -> dict:
    """
    Deterministic orchestration entry point.

    Exact execution order mandated by specification:
    1.  Load session or initialize.
    2.  If INIT → route intent deterministically.
    3.  Call ContextWeave.analyze() under defined conditions only.
    4.  Update slots exclusively from slot_updates.
    5.  Increment iteration_count.
    6.  Recompute missing_slots deterministically.
    7.  Evaluate stopping conditions → READY_FOR_VALIDATION if met.
    8.  If READY_FOR_VALIDATION → call ContextWeave.final_validation().
    9.  Apply decision engine rule table.
    10. If EXECUTE → call ToolWeave.execute().
    11. Apply persona transform to user_message only.
    12. Return strict output object.
    """
    if _context_weave is None or _tool_weave is None:
        raise RuntimeError(
            "Clients not configured. Call intentweave.orchestrator.configure() first."
        )

    active_store = _store if _store is not None else _default_store

    # ------------------------------------------------------------------
    # Step 1 — Load or initialise session
    # ------------------------------------------------------------------
    session = active_store.get(session_id)
    if session is None:
        session = _new_session(session_id, user_id, persona)

    # Guard: terminal states accept no further input
    if session.state in (State.COMPLETED, State.EXECUTING):
        session.state = State.BLOCKED
        return _blocked_response(session, active_store, reason="Session is in a terminal state.")

    # ------------------------------------------------------------------
    # Step 2 — Route intent (INIT only)
    # ------------------------------------------------------------------
    if session.state == State.INIT:
        intent = route_intent(user_message)

        if intent is None:
            # Undefined condition — spec: set BLOCKED, return safe response
            session.state = State.BLOCKED
            active_store.save(session)
            return _blocked_response(
                session, active_store, reason="Intent could not be determined from the message."
            )

        config = get_intent_config(intent)
        session.intent = intent
        session.domain = config["domain"]
        session.required_slots = list(config["required_slots"])
        # ROUTED is a transient state — immediately resolve to loop state
        session.state = State.ROUTED
        session.missing_slots = compute_missing_slots(session.required_slots, session.filled_slots)
        session.state = State.CLARIFYING if session.missing_slots else State.STRUCTURING

    # ------------------------------------------------------------------
    # Step 3 — Call ContextWeave.analyze() under defined conditions only
    # ------------------------------------------------------------------
    analysis: dict | None = None
    consecutive_empty: int = active_store.get_metadata(session_id).get(
        "consecutive_empty_updates", 0
    )

    can_analyze = (
        session.state in (State.CLARIFYING, State.STRUCTURING)
        and session.iteration_count < 2 * max(len(session.required_slots), 1)
    )

    if can_analyze:
        try:
            raw_analysis = _context_weave.analyze(session, user_message)
            validate_analyze_response(raw_analysis)
            analysis = raw_analysis
        except Exception:
            # Undefined condition from external API — spec: BLOCK
            session.state = State.BLOCKED
            active_store.save(session)
            return _blocked_response(
                session, active_store, reason="ContextWeave.analyze() returned an invalid response."
            )

        # ------------------------------------------------------------------
        # Step 4 — Update slots exclusively from slot_updates
        # ------------------------------------------------------------------
        slot_updates: dict = analysis.get("slot_updates", {})
        previous_filled = set(session.filled_slots.keys())
        session.filled_slots = apply_slot_updates(session.filled_slots, slot_updates)

        # Track consecutive iterations with no new slot information (SC3)
        new_keys = set(session.filled_slots.keys()) - previous_filled
        if new_keys:
            consecutive_empty = 0
        else:
            consecutive_empty += 1
        active_store.set_metadata(session_id, "consecutive_empty_updates", consecutive_empty)

        # ------------------------------------------------------------------
        # Step 5 — Increment iteration_count
        # ------------------------------------------------------------------
        session.iteration_count += 1

        # ------------------------------------------------------------------
        # Step 6 — Recompute missing_slots deterministically
        # ------------------------------------------------------------------
        session.missing_slots = compute_missing_slots(session.required_slots, session.filled_slots)

        # Sync state: if missing_slots cleared, move to STRUCTURING
        if not session.missing_slots and session.state == State.CLARIFYING:
            session.state = State.STRUCTURING

        # ------------------------------------------------------------------
        # Step 7 — Evaluate stopping conditions
        # ------------------------------------------------------------------
        if _stopping_condition_met(session, consecutive_empty):
            session.state = State.READY_FOR_VALIDATION

    elif session.state in (State.CLARIFYING, State.STRUCTURING):
        # Iteration limit already reached (step 3 condition failed).
        # SC2 forces transition.
        session.state = State.READY_FOR_VALIDATION

    # ------------------------------------------------------------------
    # Step 8 — Final validation (mandatory before execution)
    # ------------------------------------------------------------------
    validation_result: dict | None = None
    questions: list[str] = analysis.get("questions", []) if analysis else []

    if session.state == State.READY_FOR_VALIDATION:
        try:
            raw_validation = _context_weave.final_validation(session)
            validate_final_validation_response(raw_validation)
            validation_result = raw_validation
        except Exception:
            session.state = State.BLOCKED
            active_store.save(session)
            return _blocked_response(
                session,
                active_store,
                reason="ContextWeave.final_validation() returned an invalid response.",
            )

        all_execution_conditions_met = (
            validation_result["allowed"] is True
            and validation_result["confidence_score"] >= 0.9
            and len(session.missing_slots) == 0
        )

        if all_execution_conditions_met:
            session.state = State.READY_FOR_EXECUTION
        elif not validation_result["allowed"]:
            session.state = State.BLOCKED
        else:
            # Confidence too low — return to clarifying if within limits
            if session.iteration_count < 2 * max(len(session.required_slots), 1):
                session.state = State.CLARIFYING
            else:
                session.state = State.BLOCKED

    # ------------------------------------------------------------------
    # Step 9 — Apply decision engine rule table
    # ------------------------------------------------------------------
    action = decide(session)

    # ------------------------------------------------------------------
    # Step 10 — Execute via ToolWeave (EXECUTE action only)
    # ------------------------------------------------------------------
    tool_result: dict | None = None
    if action == Action.EXECUTE:
        session.state = State.EXECUTING
        tool_name = get_tool_name(session.intent)
        payload = dict(session.filled_slots)  # payload sourced only from filled_slots

        try:
            tool_result = _tool_weave.execute(tool_name, payload)
        except Exception:
            session.state = State.BLOCKED
            active_store.save(session)
            return _blocked_response(
                session, active_store, reason="ToolWeave.execute() raised an exception."
            )

        session.state = State.COMPLETED

    elif action == Action.PRESENT:
        session.state = State.COMPLETED

    # ------------------------------------------------------------------
    # Step 11 — Build neutral message, then apply persona transform only
    # ------------------------------------------------------------------
    confidence: float = (
        analysis["confidence_score"] if analysis
        else (validation_result["confidence_score"] if validation_result else 0.0)
    )

    raw_message = _build_raw_message(
        action, session, questions, tool_result, validation_result
    )
    system_transparency = _build_system_transparency(
        action, session, analysis, validation_result
    )

    user_message_out = transform(raw_message, session.persona)

    # ------------------------------------------------------------------
    # Step 12 — Persist and return strict output object
    # ------------------------------------------------------------------
    active_store.save(session)

    return {
        "user_message": user_message_out,
        "system_transparency": system_transparency,
        "state": session.state,
        "internal": {
            "intent": session.intent,
            "domain": session.domain,
            "slots": session.filled_slots,
            "missing_slots": session.missing_slots,
            "confidence": confidence,
            "iteration_count": session.iteration_count,
            "persona": session.persona,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _blocked_response(
    session: Session,
    active_store: SessionStore,
    reason: str = "",
) -> dict:
    """Safe response for any BLOCKED state. Never guesses or invents data."""
    raw_message = f"Your request cannot be processed. {reason}".strip()
    user_message_out = transform(raw_message, session.persona)
    active_store.save(session)
    return {
        "user_message": user_message_out,
        "system_transparency": f"action=BLOCK | state={session.state} | reason={reason}",
        "state": session.state,
        "internal": {
            "intent": session.intent,
            "domain": session.domain,
            "slots": session.filled_slots,
            "missing_slots": session.missing_slots,
            "confidence": 0.0,
            "iteration_count": session.iteration_count,
            "persona": session.persona,
        },
    }
