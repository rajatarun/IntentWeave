from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Session:
    session_id: str
    user_id: str
    intent: str | None
    domain: str | None
    state: str
    iteration_count: int
    required_slots: list[str]
    filled_slots: dict
    missing_slots: list[str]
    persona: str
