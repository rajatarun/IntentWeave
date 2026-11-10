#!/usr/bin/env python3
"""Run IntentWeave thread create/continue locally (mock provider, in-memory store).

No AWS account or API keys required.

Usage:
    pip install -r requirements-dev.txt
    PYTHONPATH=src python3 examples/local_thread_lifecycle.py
"""

from intentweave.clock import FakeClock
from intentweave.providers.mock import MockProvider
from intentweave.service import ThreadService
from intentweave.store.memory import MemoryThreadStore

CREATE = {
    "model": "claude-test-1",
    "max_tokens": 256,
    "cache_control": {"type": "ephemeral"},
    "system": "You are helpful.",
    "messages": [{"role": "user", "content": "Hello"}],
    "thread": {"type": "create"},
}

CONTINUE = {
    "model": "claude-test-1",
    "max_tokens": 256,
    "cache_control": {"type": "ephemeral"},
    "messages": [{"role": "user", "content": "Follow up"}],
    "thread": {"type": "continue", "previous_message_id": ""},  # filled after create
}


def main() -> None:
    service = ThreadService(
        MemoryThreadStore(),
        MockProvider(),
        FakeClock(start=1_700_000_000.0),
    )
    first = service.handle_messages(CREATE)
    print("create:", first["id"], first["content"][0]["text"])

    body = {**CONTINUE, "thread": {"type": "continue", "previous_message_id": first["id"]}}
    second = service.handle_messages(body)
    print("continue:", second["id"], second["content"][0]["text"])


if __name__ == "__main__":
    main()
