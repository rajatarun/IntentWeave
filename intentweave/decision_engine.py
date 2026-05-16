from __future__ import annotations

from intentweave.intent_registry import intent_needs_tool
from intentweave.states import State


class Action:
    ASK = "ASK"
    VALIDATE = "VALIDATE"
    EXECUTE = "EXECUTE"
    BLOCK = "BLOCK"
    PRESENT = "PRESENT"


def decide(session) -> str:
    """
    Apply the hard decision-rule table in strict priority order.
    Returns exactly one Action constant.

    Table (in priority order):
    1. missing_slots not empty       → ASK
    2. state == READY_FOR_EXECUTION, needs tool  → EXECUTE
    3. state == READY_FOR_EXECUTION, no tool     → PRESENT
    4. state == BLOCKED              → BLOCK
    5. any other state with missing  → ASK  (already caught by rule 1)
    6. undefined condition           → BLOCK
    """
    # Rule 1 (highest priority)
    if session.missing_slots:
        return Action.ASK

    # Rules 2 & 3: execution gate — state must be READY_FOR_EXECUTION
    if session.state == State.READY_FOR_EXECUTION:
        if intent_needs_tool(session.intent):
            return Action.EXECUTE
        return Action.PRESENT

    # Rule 4: blocked
    if session.state == State.BLOCKED:
        return Action.BLOCK

    # States where we are still collecting (no missing slots means
    # stopping condition was hit but state transition hasn't completed — block)
    if session.state in (State.CLARIFYING, State.STRUCTURING):
        return Action.ASK

    # Undefined condition — spec mandates BLOCK
    return Action.BLOCK
