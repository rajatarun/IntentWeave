import pytest

from conftest import base_create_body
from intentweave.clock import FakeClock
from intentweave.errors import ThreadError
from intentweave.providers.mock import MockProvider
from intentweave.service import ThreadService
from intentweave.store.memory import MemoryThreadStore


def test_soft_ttl_expiry():
    clock = FakeClock(start=1_700_000_000.0)
    store = MemoryThreadStore()
    service = ThreadService(
        store, MockProvider(), clock, soft_ttl_seconds=300, hard_ttl_seconds=3600
    )
    first = service.handle_messages(base_create_body())

    clock.advance(301)
    with pytest.raises(ThreadError) as exc:
        service.handle_messages(
            {
                "model": "claude-test-1",
                "max_tokens": 256,
                "cache_control": {"type": "ephemeral"},
                "messages": [{"role": "user", "content": "Late"}],
                "thread": {"type": "continue", "previous_message_id": first["id"]},
            }
        )
    assert exc.value.error_code == "thread_not_found"


def test_ttl_reset_on_continue():
    clock = FakeClock(start=1_700_000_000.0)
    store = MemoryThreadStore()
    service = ThreadService(
        store, MockProvider(), clock, soft_ttl_seconds=300, hard_ttl_seconds=3600
    )
    first = service.handle_messages(base_create_body())
    clock.advance(200)
    second = service.handle_messages(
        {
            "model": "claude-test-1",
            "max_tokens": 256,
            "cache_control": {"type": "ephemeral"},
            "messages": [{"role": "user", "content": "Still ok"}],
            "thread": {"type": "continue", "previous_message_id": first["id"]},
        }
    )
    rec = store.get(second["id"])
    assert rec is not None
    assert rec.last_used_epoch == clock.now()
    assert rec.ttl_epoch == int(clock.now()) + 3600
