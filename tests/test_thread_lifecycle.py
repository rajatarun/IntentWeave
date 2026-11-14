import pytest

from conftest import base_create_body
from intentweave.errors import ThreadError
from intentweave.fingerprint import history_digest
from intentweave.models import ThreadRecord
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


def test_routed_continue_different_model(service: ThreadService, store):
    first = service.handle_messages(base_create_body())
    rec = store.get(first["id"])
    assert rec is not None
    assert rec.model_policy == "routed"

    second = service.handle_messages(
        {
            "model": "claude-other",
            "max_tokens": 256,
            "cache_control": {"type": "ephemeral"},
            "messages": [{"role": "user", "content": "Follow up"}],
            "thread": {"type": "continue", "previous_message_id": first["id"]},
        }
    )
    assert "mock:claude-other:" in second["content"][0]["text"]
    child = store.get(second["id"])
    assert child is not None
    assert child.model == "claude-other"
    assert child.messages[-1]["model"] == "claude-other"
    assert child.messages[-1]["provider"] == "mock"
    assert child.messages[1]["model"] == "claude-test-1"


def test_pinned_continue_rejects_model_change(service: ThreadService):
    first = service.handle_messages(
        base_create_body(thread={"type": "create", "model_policy": "pinned"})
    )
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
    assert exc.value.error_code == "thread_model_policy_violation"


def test_legacy_thread_validates_and_pins_model(service: ThreadService, store, clock):
    system = "You are helpful."
    messages = [
        {"role": "user", "content": "Hello"},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "hi"}],
            "model": "claude-test-1",
            "provider": "mock",
        },
    ]
    legacy_fp = {
        "model": "claude-test-1",
        "cache_control": {"type": "ephemeral"},
        "history_digest": history_digest(system=system, messages=messages),
    }
    record = ThreadRecord(
        response_id="msg_legacy",
        thread_id="msg_legacy",
        parent_response_id=None,
        fingerprint=legacy_fp,
        system=system,
        tools=None,
        messages=messages,
        model="claude-test-1",
        provider="mock",
        model_policy="pinned",
        pinned_model="claude-test-1",
        stop_reason="end_turn",
        assistant_message={"id": "msg_legacy"},
        last_used_epoch=clock.now(),
        ttl_epoch=int(clock.now()) + 3600,
    )
    store.put(record)

    ok = service.handle_messages(
        {
            "model": "claude-test-1",
            "max_tokens": 256,
            "cache_control": {"type": "ephemeral"},
            "messages": [{"role": "user", "content": "Next"}],
            "thread": {"type": "continue", "previous_message_id": "msg_legacy"},
        }
    )
    assert ok["model"] == "claude-test-1"

    record2 = ThreadRecord(
        response_id="msg_legacy2",
        thread_id="msg_legacy2",
        parent_response_id=None,
        fingerprint=legacy_fp,
        system=system,
        tools=None,
        messages=messages,
        model="claude-test-1",
        provider="mock",
        model_policy="pinned",
        pinned_model="claude-test-1",
        stop_reason="end_turn",
        assistant_message={"id": "msg_legacy2"},
        last_used_epoch=clock.now(),
        ttl_epoch=int(clock.now()) + 3600,
    )
    store.put(record2)
    with pytest.raises(ThreadError) as exc:
        service.handle_messages(
            {
                "model": "claude-other",
                "max_tokens": 256,
                "cache_control": {"type": "ephemeral"},
                "messages": [{"role": "user", "content": "Next"}],
                "thread": {"type": "continue", "previous_message_id": "msg_legacy2"},
            }
        )
    assert exc.value.error_code == "thread_model_policy_violation"


def test_tampered_history_rejected(service: ThreadService, store, clock):
    first = service.handle_messages(base_create_body())
    rec = store.get(first["id"])
    assert rec is not None
    rec.messages = [{"role": "user", "content": "tampered"}]
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
    assert exc.value.error_code == "thread_history_integrity_violation"


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
                "model": "claude-test-1",
                "max_tokens": 256,
                "cache_control": {"type": "persistent"},
                "messages": [{"role": "user", "content": "Next"}],
                "thread": {"type": "continue", "previous_message_id": first["id"]},
            }
        )
    assert exc.value.error_code == "thread_fingerprint_mismatch"
    assert "cache_control" in exc.value.details.get("mismatched_fields", [])


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
