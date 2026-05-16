from __future__ import annotations

from abc import ABC, abstractmethod

from intentweave.models import Session


class ContextWeaveClient(ABC):
    """Stateless analysis and validation API. External only."""

    @abstractmethod
    def analyze(self, session: Session, user_message: str) -> dict:
        """
        Contract: returns exactly:
        {
            "missing_slots":     list[str],
            "slot_updates":      dict,
            "questions":         list[str],
            "confidence_score":  float,   # 0.0–1.0
            "ambiguity_score":   float,   # 0.0–1.0
        }
        """

    @abstractmethod
    def final_validation(self, session: Session) -> dict:
        """
        Contract: returns exactly:
        {
            "allowed":           bool,
            "confidence_score":  float,
            "risk_score":        float,
            "policy_flags":      list[str],
        }
        """


class ToolWeaveClient(ABC):
    """Stateless execution API. External only."""

    @abstractmethod
    def execute(self, tool_name: str, payload: dict) -> dict:
        """Execute the named tool with a payload sourced exclusively from filled_slots."""


_REQUIRED_ANALYZE_KEYS: frozenset[str] = frozenset({
    "missing_slots",
    "slot_updates",
    "questions",
    "confidence_score",
    "ambiguity_score",
})

_REQUIRED_VALIDATION_KEYS: frozenset[str] = frozenset({
    "allowed",
    "confidence_score",
    "risk_score",
    "policy_flags",
})


def validate_analyze_response(response: dict) -> None:
    """Raise ValueError if the analyze() response violates the contract."""
    if not isinstance(response, dict):
        raise ValueError("analyze() must return a dict")
    missing = _REQUIRED_ANALYZE_KEYS - response.keys()
    if missing:
        raise ValueError(f"analyze() response missing keys: {missing}")


def validate_final_validation_response(response: dict) -> None:
    """Raise ValueError if the final_validation() response violates the contract."""
    if not isinstance(response, dict):
        raise ValueError("final_validation() must return a dict")
    missing = _REQUIRED_VALIDATION_KEYS - response.keys()
    if missing:
        raise ValueError(f"final_validation() response missing keys: {missing}")
