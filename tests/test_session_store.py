"""Tests for the thread-safe in-memory SessionStore."""
from __future__ import annotations

import threading

import pytest

from intentweave.session_store import SessionStore
from intentweave.states import State
from tests.conftest import make_session


@pytest.fixture
def store():
    return SessionStore()


class TestGetAndSave:
    def test_get_missing_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_save_and_retrieve(self, store):
        s = make_session(session_id="s1")
        store.save(s)
        retrieved = store.get("s1")
        assert retrieved is s

    def test_save_overwrites_previous(self, store):
        s1 = make_session(session_id="s1", state=State.CLARIFYING)
        store.save(s1)
        s1.state = State.READY_FOR_VALIDATION
        store.save(s1)
        assert store.get("s1").state == State.READY_FOR_VALIDATION


class TestDelete:
    def test_delete_removes_session(self, store):
        s = make_session(session_id="s1")
        store.save(s)
        store.delete("s1")
        assert store.get("s1") is None

    def test_delete_nonexistent_is_noop(self, store):
        store.delete("ghost")  # must not raise


class TestMetadata:
    def test_get_metadata_returns_empty_for_unknown(self, store):
        assert store.get_metadata("no-session") == {}

    def test_set_and_get_metadata(self, store):
        store.set_metadata("s1", "consecutive_empty_updates", 1)
        assert store.get_metadata("s1")["consecutive_empty_updates"] == 1

    def test_metadata_updated_independently(self, store):
        store.set_metadata("s1", "key", 0)
        store.set_metadata("s1", "key", 2)
        assert store.get_metadata("s1")["key"] == 2

    def test_delete_also_removes_metadata(self, store):
        store.set_metadata("s1", "k", 99)
        store.delete("s1")
        assert store.get_metadata("s1") == {}


class TestReset:
    def test_reset_clears_all(self, store):
        store.save(make_session(session_id="s1"))
        store.save(make_session(session_id="s2"))
        store.set_metadata("s1", "k", 1)
        store.reset()
        assert store.get("s1") is None
        assert store.get("s2") is None
        assert store.get_metadata("s1") == {}


class TestThreadSafety:
    def test_concurrent_saves_do_not_corrupt(self, store):
        errors = []

        def save_many(prefix: str):
            try:
                for i in range(50):
                    s = make_session(session_id=f"{prefix}-{i}")
                    store.save(s)
                    _ = store.get(f"{prefix}-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_many, args=(f"t{n}",)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
