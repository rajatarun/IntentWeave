from __future__ import annotations


class State:
    INIT = "INIT"
    ROUTED = "ROUTED"
    CLARIFYING = "CLARIFYING"
    STRUCTURING = "STRUCTURING"
    READY_FOR_VALIDATION = "READY_FOR_VALIDATION"
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"

    _ALL: frozenset[str] = frozenset({
        INIT, ROUTED, CLARIFYING, STRUCTURING,
        READY_FOR_VALIDATION, READY_FOR_EXECUTION,
        EXECUTING, COMPLETED, BLOCKED,
    })

    @classmethod
    def is_valid(cls, state: str) -> bool:
        return state in cls._ALL
