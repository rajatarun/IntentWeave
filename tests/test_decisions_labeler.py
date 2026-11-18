import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import base_create_body
from intentweave.intent_decisions import (
    DecisionsLabelerConfig,
    label_with_decisions,
    parse_decisions_response,
)
from intentweave.intent_heuristic import label_heuristic
from intentweave.intent_labeler import IntentLabeler
from intentweave.service import ThreadService


def _fake_result(answers: dict) -> SimpleNamespace:
    wrapped = {k: SimpleNamespace(**v) for k, v in answers.items()}

    class _Answers:
        def get(self, key, default=None):
            return wrapped.get(key, default)

    return SimpleNamespace(answers=_Answers())


def test_flag_off_no_intent_fields(service: ThreadService):
    body = base_create_body()
    result = service.handle_messages(body)
    assert "intent_label" not in result
    assert "intent_decision_source" not in result


def test_flag_on_heuristic_without_api_key(service, monkeypatch):
    monkeypatch.setenv("INTENTWEAVE_DECISIONS_LABELER", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    labeler = IntentLabeler(decisions_enabled=True, gemini_api_key=None)
    svc = ThreadService(
        service._store,
        service._provider,
        service._clock,
        soft_ttl_seconds=service._soft_ttl,
        hard_ttl_seconds=service._hard_ttl,
        provider_name=service._provider_name,
        intent_labeler=labeler,
    )
    result = svc.handle_messages(base_create_body(messages=[{"role": "user", "content": "Hello!"}]))
    assert result["intent_label"] == "small_talk"
    assert result["intent_decision_source"] == "heuristic"


def test_parse_low_confidence_returns_none():
    raw = _fake_result(
        {
            "intent": {"type": "choice", "choice": "task", "confidence": 0.2},
            "is_small_talk": {"type": "noul", "noul": 0.1, "confidence": 0.9},
        }
    )
    assert parse_decisions_response(raw, min_confidence=0.5) is None


def test_parse_small_talk_noul_wins():
    raw = _fake_result(
        {
            "intent": {"type": "choice", "choice": "task", "confidence": 0.99},
            "is_small_talk": {"type": "noul", "noul": 0.95, "confidence": 0.9},
        }
    )
    parsed = parse_decisions_response(raw, min_confidence=0.5)
    assert parsed is not None
    assert parsed.label == "small_talk"
    assert parsed.source == "gemini_decisions"


def test_decisions_api_error_falls_back():
    client = MagicMock()
    client.create.side_effect = RuntimeError("network")

    config = DecisionsLabelerConfig(api_key="test-key", timeout_s=1.5, min_confidence=0.5)
    result = label_with_decisions(
        messages=[{"role": "user", "content": "What is the capital of France?"}],
        resume_pause=False,
        client=client,
        config=config,
    )
    expected = label_heuristic(
        messages=[{"role": "user", "content": "What is the capital of France?"}]
    )
    assert result.label == expected.label
    assert result.source == "gemini_decisions_fallback"


def test_decisions_timeout_falls_back():
    client = MagicMock()

    def slow_create(**_kwargs):
        import time

        time.sleep(2.0)
        return _fake_result({})

    client.create.side_effect = slow_create
    config = DecisionsLabelerConfig(api_key="test-key", timeout_s=0.05, min_confidence=0.5)
    result = label_with_decisions(
        messages=[{"role": "user", "content": "Build me a REST API"}],
        resume_pause=False,
        client=client,
        config=config,
    )
    assert result.source == "gemini_decisions_fallback"


def test_decisions_malformed_falls_back():
    client = MagicMock()
    client.create.return_value = {"answers": {}}
    config = DecisionsLabelerConfig(api_key="test-key", timeout_s=1.5, min_confidence=0.5)
    result = label_with_decisions(
        messages=[{"role": "user", "content": "Thanks!"}],
        resume_pause=False,
        client=client,
        config=config,
    )
    assert result.source == "gemini_decisions_fallback"


def test_decisions_success_attaches_fields(store, clock):
    client = MagicMock()
    client.create.return_value = _fake_result(
        {
            "intent": {"type": "choice", "choice": "question", "confidence": 0.91},
            "is_small_talk": {"type": "noul", "noul": 0.05, "confidence": 0.95},
        }
    )
    labeler = IntentLabeler(decisions_enabled=True, gemini_api_key="key", client=client)
    from intentweave.providers.mock import MockProvider

    svc = ThreadService(
        store,
        MockProvider(),
        clock,
        intent_labeler=labeler,
    )

    out = svc.handle_messages(
        base_create_body(messages=[{"role": "user", "content": "Who invented the telephone?"}])
    )
    assert out["intent_label"] == "question"
    assert out["intent_decision_source"] == "gemini_decisions"
    assert out["intent_confidence"] == 0.91
    client.create.assert_called_once()


@pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") and os.environ.get("WEAVE_DECISIONS_LIVE") == "1"),
    reason="Set GEMINI_API_KEY and WEAVE_DECISIONS_LIVE=1 for a paid live smoke test",
)
def test_live_gemini_decisions_smoke():
    from intentweave.intent_decisions import build_genai_client

    api_key = os.environ["GEMINI_API_KEY"]
    client = build_genai_client(api_key)
    config = DecisionsLabelerConfig(api_key=api_key, timeout_s=5.0, min_confidence=0.5)
    result = label_with_decisions(
        messages=[{"role": "user", "content": "Hi there!"}],
        resume_pause=False,
        client=client,
        config=config,
    )
    assert result.label in {"small_talk", "other", "continuation"}
