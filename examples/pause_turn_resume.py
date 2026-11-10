#!/usr/bin/env python3
"""Demonstrate pause_turn and resume with an empty messages array."""

from intentweave.clock import FakeClock
from intentweave.providers.mock import MockProvider
from intentweave.service import ThreadService
from intentweave.store.memory import MemoryThreadStore

PAUSE_MARKER = "__intentweave_pause__"


def main() -> None:
    service = ThreadService(MemoryThreadStore(), MockProvider(), FakeClock())
    created = service.handle_messages(
        {
            "model": "claude-test-1",
            "max_tokens": 256,
            "cache_control": {"type": "ephemeral"},
            "messages": [{"role": "user", "content": PAUSE_MARKER}],
            "thread": {"type": "create"},
        }
    )
    assert created["stop_reason"] == "pause_turn", created
    paused_id = created["id"]

    resumed = service.handle_messages(
        {
            "model": "claude-test-1",
            "max_tokens": 256,
            "cache_control": {"type": "ephemeral"},
            "messages": [],
            "thread": {"type": "continue", "previous_message_id": paused_id},
        }
    )
    print("paused:", paused_id, "stop_reason=", created["stop_reason"])
    print("resumed:", resumed["id"], resumed["content"][0]["text"])


if __name__ == "__main__":
    main()
