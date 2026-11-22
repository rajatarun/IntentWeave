"""Tests for standalone IntentWeave SQLiteThreadStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from intentweave.clock import FakeClock
from intentweave.errors import ThreadError
from intentweave.providers.mock import MockProvider
from intentweave.service import ThreadService
from intentweave.store import SQLiteThreadStore


def test_sqlite_thread_store_multi_turn_persists_across_restarts(tmp_path: Path) -> None:
    db_path = tmp_path / "threads.sqlite3"
    clock = FakeClock(1_700_000_000.0)
    store1 = SQLiteThreadStore(db_path)
    svc1 = ThreadService(store=store1, provider=MockProvider(), clock=clock)

    turn1 = svc1.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Hello"}],
            "thread": {"type": "create"},
        }
    )
    resp_id = turn1["id"]
    store1.close()

    # Re-open from disk and continue the thread.
    clock.advance(5.0)
    store2 = SQLiteThreadStore(db_path)
    svc2 = ThreadService(store=store2, provider=MockProvider(), clock=clock)
    turn2 = svc2.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Follow up"}],
            "thread": {"type": "continue", "previous_message_id": resp_id},
        }
    )
    assert turn2["id"] != resp_id

    # Re-continuing an already continued message_id must fail cleanly.
    with pytest.raises(ThreadError):
        svc2.handle_messages(
            {
                "model": "mock-local",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "Replay"}],
                "thread": {"type": "continue", "previous_message_id": resp_id},
            }
        )
    store2.close()
