import pytest

from conftest import base_create_body
from intentweave.errors import ThreadError
from intentweave.service import ThreadService


def test_create_then_continue(service: ThreadService):
    first = service.handle_messages(base_create_body())
    assert first["role"] == "assistant"
    assert first["id"].startswith("msg_")

    second = service.handle_messages(
        {
            "model": "claude-test-1",
            "max_tokens": 256,
            "cache_control": {"type": "ephemeral"},
            "messages": [{"role": "user", "content": "Follow up"}],
            "thread": {"type": "continue", "previous_message_id": first["id"]},
        }
    )
    assert "mock:claude-test-1:3 turns" in second["content"][0]["text"]


def test_already_continued(service: ThreadService):
    first = service.handle_messages(base_create_body())
    service.handle_messages(
        {
            "model": "claude-test-1",
            "max_tokens": 256,
            "cache_control": {"type": "ephemeral"},
            "messages": [{"role": "user", "content": "Next"}],
            "thread": {"type": "continue", "previous_message_id": first["id"]},
        }
    )
    with pytest.raises(ThreadError) as exc:
        service.handle_messages(
            {
                "model": "claude-test-1",
                "max_tokens": 256,
                "cache_control": {"type": "ephemeral"},
                "messages": [{"role": "user", "content": "Again"}],
                "thread": {"type": "continue", "previous_message_id": first["id"]},
            }
        )
    assert exc.value.error_code == "thread_already_continued"


def test_not_found(service: ThreadService):
    with pytest.raises(ThreadError) as exc:
        service.handle_messages(
            {
                "model": "claude-test-1",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": "x"}],
                "thread": {"type": "continue", "previous_message_id": "msg_missing"},
            }
        )
    assert exc.value.error_code == "thread_not_found"
    assert exc.value.http_status == 404


def test_fingerprint_mismatch(service: ThreadService):
    first = service.handle_messages(base_create_body())
    with pytest.raises(ThreadError) as exc:
        service.handle_messages(
            {
                "model": "claude-other",
                "max_tokens": 256,
                "cache_control": {"type": "ephemeral"},
                "messages": [{"role": "user", "content": "Next"}],
                "thread": {"type": "continue", "previous_message_id": first["id"]},
            }
        )
    assert exc.value.error_code == "thread_fingerprint_mismatch"
    assert "model" in exc.value.details.get("mismatched_fields", [])


def test_reject_system_on_continue(service: ThreadService):
    first = service.handle_messages(base_create_body())
    with pytest.raises(ThreadError) as exc:
        service.handle_messages(
            {
                "model": "claude-test-1",
                "max_tokens": 256,
                "system": "Nope",
                "messages": [{"role": "user", "content": "Next"}],
                "thread": {"type": "continue", "previous_message_id": first["id"]},
            }
        )
    assert exc.value.http_status == 400
    assert exc.value.error_code is None


def test_continue_in_flight(service: ThreadService, store):

    first = service.handle_messages(base_create_body())
    rec = store.get(first["id"])
    assert rec is not None
    rec.continue_in_flight = True
    store.put(rec)

    with pytest.raises(ThreadError) as exc:
        service.handle_messages(
            {
                "model": "claude-test-1",
                "max_tokens": 256,
                "cache_control": {"type": "ephemeral"},
                "messages": [{"role": "user", "content": "Next"}],
                "thread": {"type": "continue", "previous_message_id": first["id"]},
            }
        )
    assert exc.value.error_code == "thread_continue_in_flight"
