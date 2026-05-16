from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any

from intentweave.models import Session


class AbstractSessionStore(ABC):
    """
    Contract all session-store backends must satisfy.
    IntentWeave is the ONLY stateful system — all state lives here.
    """

    @abstractmethod
    def get(self, session_id: str) -> Session | None:
        """Return the session or None if it does not exist."""

    @abstractmethod
    def save(self, session: Session) -> None:
        """Persist (create or overwrite) the session."""

    @abstractmethod
    def delete(self, session_id: str) -> None:
        """Remove the session and its metadata. No-op if absent."""

    @abstractmethod
    def get_metadata(self, session_id: str) -> dict[str, Any]:
        """Return a copy of the session's runtime metadata dict."""

    @abstractmethod
    def set_metadata(self, session_id: str, key: str, value: Any) -> None:
        """Set one key in the session's runtime metadata."""

    def reset(self) -> None:
        """Wipe all sessions. Intended for tests; not safe for production stores."""
        raise NotImplementedError("reset() is not supported by this store backend")


class SessionStore(AbstractSessionStore):
    """
    Thread-safe in-memory store.

    Stores Session objects and per-session runtime metadata that must not
    pollute the Session schema (e.g., consecutive-empty-update counters).
    Used for local development, tests, and single-process deployments.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

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

    def get_metadata(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._metadata.get(session_id, {}))

    def set_metadata(self, session_id: str, key: str, value: Any) -> None:
        with self._lock:
            if session_id not in self._metadata:
                self._metadata[session_id] = {}
            self._metadata[session_id][key] = value

    def reset(self) -> None:
        """Clear all sessions and metadata. Tests only."""
        with self._lock:
            self._sessions.clear()
            self._metadata.clear()


# Module-level singleton for local/in-process use.
# Lambda deployments replace this with DynamoDBSessionStore.
store: SessionStore = SessionStore()
