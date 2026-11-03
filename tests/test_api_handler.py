import json

from intentweave.api import lambda_handler
from intentweave.clock import FakeClock
from intentweave.providers.mock import MockProvider
from intentweave.service import ThreadService
from intentweave.store.memory import MemoryThreadStore


def _service():
    return ThreadService(
        MemoryThreadStore(),
        MockProvider(),
        FakeClock(),
        soft_ttl_seconds=300,
        hard_ttl_seconds=3600,
    )


def test_health_route():
    event = {"rawPath": "/health", "requestContext": {"http": {"method": "GET"}}}
    resp = lambda_handler(event, None, _service())
    assert resp["statusCode"] == 200


def test_health_route_with_stage_prefix():
    event = {
        "rawPath": "/prod/health",
        "requestContext": {"stage": "prod", "http": {"method": "GET"}},
    }
    resp = lambda_handler(event, None, _service())
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"status": "ok"}


def test_messages_route():
    body = {
        "model": "claude-test-1",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "hi"}],
        "thread": {"type": "create"},
    }
    event = {
        "rawPath": "/v1/messages",
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps(body),
    }
    resp = lambda_handler(event, None, _service())
    assert resp["statusCode"] == 200
    payload = json.loads(resp["body"])
    assert payload["type"] == "message"


def test_messages_route_with_stage_prefix():
    body = {
        "model": "claude-test-1",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "hi"}],
        "thread": {"type": "create"},
    }
    event = {
        "rawPath": "/prod/v1/messages",
        "requestContext": {"stage": "prod", "http": {"method": "POST"}},
        "body": json.dumps(body),
    }
    resp = lambda_handler(event, None, _service())
    assert resp["statusCode"] == 200
    payload = json.loads(resp["body"])
    assert payload["type"] == "message"
