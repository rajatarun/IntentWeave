import pytest

from conftest import base_create_body
from intentweave.errors import ThreadError
from intentweave.providers.mock import _PAUSE_MARKER, _REFUSAL_MARKER
from intentweave.service import ThreadService


def test_pause_turn_resume(service: ThreadService):
    paused = service.handle_messages(
        base_create_body(messages=[{"role": "user", "content": _PAUSE_MARKER}])
    )
    assert paused["stop_reason"] == "pause_turn"

    resumed = service.handle_messages(
        {
            "model": "claude-test-1",
            "max_tokens": 256,
            "cache_control": {"type": "ephemeral"},
            "messages": [],
            "thread": {"type": "continue", "previous_message_id": paused["id"]},
        }
    )
    assert resumed["stop_reason"] == "end_turn"


def test_pause_rejects_new_user_message(service: ThreadService):
    paused = service.handle_messages(
        base_create_body(messages=[{"role": "user", "content": _PAUSE_MARKER}])
    )
    with pytest.raises(ThreadError) as exc:
        service.handle_messages(
            {
                "model": "claude-test-1",
                "max_tokens": 256,
                "cache_control": {"type": "ephemeral"},
                "messages": [{"role": "user", "content": "too soon"}],
                "thread": {"type": "continue", "previous_message_id": paused["id"]},
            }
        )
    assert exc.value.http_status == 400


def test_refusal_not_continuable(service: ThreadService):
    refused = service.handle_messages(
        base_create_body(messages=[{"role": "user", "content": _REFUSAL_MARKER}])
    )
    assert refused["stop_reason"] == "refusal"
    with pytest.raises(ThreadError) as exc:
        service.handle_messages(
            {
                "model": "claude-test-1",
                "max_tokens": 256,
                "cache_control": {"type": "ephemeral"},
                "messages": [{"role": "user", "content": "please?"}],
                "thread": {"type": "continue", "previous_message_id": refused["id"]},
            }
        )
    assert exc.value.error_code == "thread_not_found"
