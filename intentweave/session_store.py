from __future__ import annotations

import threading
from typing import Any

from intentweave.models import Session


class SessionStore:
    """
    Thread-safe in-memory session store.

    Stores Session objects and per-session runtime metadata that must not
    pollute the Session schema (e.g., consecutive-empty-update counters).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def save(self, session: Session) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
            self._metadata.pop(session_id, None)

    # ------------------------------------------------------------------
    # Runtime metadata (does not touch Session schema)
    # ------------------------------------------------------------------

    def get_metadata(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._metadata.get(session_id, {}))

    def set_metadata(self, session_id: str, key: str, value: Any) -> None:
        with self._lock:
            if session_id not in self._metadata:
                self._metadata[session_id] = {}
            self._metadata[session_id][key] = value

    def reset(self) -> None:
        """Clear all sessions and metadata. Intended for tests only."""
        with self._lock:
            self._sessions.clear()
            self._metadata.clear()


# Module-level singleton used by the orchestrator.
store: SessionStore = SessionStore()
