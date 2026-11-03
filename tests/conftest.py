import pytest

from intentweave.clock import FakeClock
from intentweave.providers.mock import MockProvider
from intentweave.service import ThreadService
from intentweave.store.memory import MemoryThreadStore


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(start=1_700_000_000.0)


@pytest.fixture
def store() -> MemoryThreadStore:
    return MemoryThreadStore()


@pytest.fixture
def service(store: MemoryThreadStore, clock: FakeClock) -> ThreadService:
    return ThreadService(
        store,
        MockProvider(),
        clock,
        soft_ttl_seconds=300,
        hard_ttl_seconds=3600,
    )


def base_create_body(**overrides):
    body = {
        "model": "claude-test-1",
        "max_tokens": 256,
        "cache_control": {"type": "ephemeral"},
        "system": "You are helpful.",
        "messages": [{"role": "user", "content": "Hello"}],
        "thread": {"type": "create"},
    }
    body.update(overrides)
    return body
