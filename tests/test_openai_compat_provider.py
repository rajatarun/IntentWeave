"""Tests for OpenAICompatProvider, registry wiring, and offline verify CLI."""

from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from intentweave.cli import main as cli_main
from intentweave.cli import verify_thread_db
from intentweave.clock import FakeClock
from intentweave.errors import ThreadError
from intentweave.providers import OpenAICompatProvider, get_provider
from intentweave.service import ThreadService
from intentweave.store.sqlite import SQLiteThreadStore


class _MockOpenAIServer:
    """Real local stdlib http.server mocking POST /v1/chat/completions."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.next_status: int = 200
        self.next_raw_body: str | None = None
        self.turn_counter: int = 0
        self.next_finish_reason: str = "stop"
        self.next_tool_calls: list[dict[str, Any]] | None = None

        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8")
                parsed = json.loads(raw) if raw else {}
                parent.requests.append(
                    {
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "content_type": self.headers.get("Content-Type"),
                        "body": parsed,
                    }
                )

                if parent.next_raw_body is not None:
                    body_bytes = parent.next_raw_body.encode("utf-8")
                    self.send_response(parent.next_status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body_bytes)))
                    self.end_headers()
                    self.wfile.write(body_bytes)
                    return

                if parent.next_status != 200:
                    err = json.dumps({"error": {"message": "upstream failure"}}).encode("utf-8")
                    self.send_response(parent.next_status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
                    return

                parent.turn_counter += 1
                msg_count = len(parsed.get("messages", []))
                message: dict[str, Any] = {
                    "role": "assistant",
                    "content": f"reply-turn-{parent.turn_counter}-msgs-{msg_count}",
                }
                if parent.next_tool_calls is not None:
                    message["tool_calls"] = parent.next_tool_calls

                response_payload = {
                    "id": f"chatcmpl_test_{parent.turn_counter}",
                    "object": "chat.completion",
                    "model": parsed.get("model", "local-qwen"),
                    "choices": [
                        {
                            "index": 0,
                            "message": message,
                            "finish_reason": parent.next_finish_reason,
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 17 * parent.turn_counter,
                        "completion_tokens": 9 * parent.turn_counter,
                        "total_tokens": 26 * parent.turn_counter,
                    },
                }
                encoded = json.dumps(response_payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> _MockOpenAIServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)


@pytest.fixture
def mock_openai_server():
    server = _MockOpenAIServer().start()
    try:
        yield server
    finally:
        server.stop()


def test_registry_resolves_openai_compat_and_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INTENTWEAVE_OPENAI_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("INTENTWEAVE_OPENAI_API_KEY", "sk-test-env")
    monkeypatch.setenv("INTENTWEAVE_OPENAI_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("INTENTWEAVE_OPENAI_TIMEOUT_S", "12.5")

    p1 = get_provider("openai_compat")
    p2 = get_provider("openai-compat")

    assert isinstance(p1, OpenAICompatProvider)
    assert isinstance(p2, OpenAICompatProvider)
    assert p1.endpoint_url == "http://127.0.0.1:11434/v1/chat/completions"
    assert p1.api_key == "sk-test-env"
    assert p1.default_model == "qwen2.5:3b"
    assert p1.timeout_s == 12.5


def test_endpoint_url_normalization():
    assert (
        OpenAICompatProvider(base_url="http://localhost:8080/").endpoint_url
        == "http://localhost:8080/v1/chat/completions"
    )
    assert (
        OpenAICompatProvider(base_url="http://localhost:8080/v1").endpoint_url
        == "http://localhost:8080/v1/chat/completions"
    )
    assert (
        OpenAICompatProvider(base_url="http://localhost:8080/v1/chat/completions").endpoint_url
        == "http://localhost:8080/v1/chat/completions"
    )


def test_request_payload_auth_header_and_usage_parsing(mock_openai_server: _MockOpenAIServer):
    provider = OpenAICompatProvider(
        base_url=mock_openai_server.base_url,
        api_key="secret-token-123",
        timeout_s=5.0,
    )
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
    result = provider.complete(
        model="qwen2.5-7b-instruct",
        messages=[{"role": "user", "content": [{"type": "text", "text": "Hello local LLM"}]}],
        system="You are a concise assistant.",
        tools=tools,
        max_tokens=256,
        request_meta={"thread": "create"},
    )

    assert len(mock_openai_server.requests) == 1
    req = mock_openai_server.requests[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["authorization"] == "Bearer secret-token-123"
    assert req["body"]["model"] == "qwen2.5-7b-instruct"
    assert req["body"]["max_tokens"] == 256
    assert req["body"]["tools"] == tools
    assert req["body"]["messages"] == [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": "Hello local LLM"},
    ]

    assert result.response_id == "chatcmpl_test_1"
    assert result.model == "qwen2.5-7b-instruct"
    assert result.stop_reason == "end_turn"
    assert result.content == [{"type": "text", "text": "reply-turn-1-msgs-2"}]
    assert result.usage == {"input_tokens": 17, "output_tokens": 9}


def test_http_error_and_invalid_response_handling(mock_openai_server: _MockOpenAIServer):
    provider = OpenAICompatProvider(base_url=mock_openai_server.base_url, timeout_s=5.0)

    # 1. Upstream HTTP 500
    mock_openai_server.next_status = 500
    with pytest.raises(ThreadError) as exc_info:
        provider.complete(
            model="local-m",
            messages=[{"role": "user", "content": "hi"}],
            system=None,
            tools=None,
            max_tokens=64,
            request_meta={},
        )
    assert exc_info.value.http_status == 502
    assert exc_info.value.error_code == "provider_http_error"
    assert exc_info.value.details["upstream_status"] == 500

    # 2. Invalid JSON body
    mock_openai_server.next_status = 200
    mock_openai_server.next_raw_body = "not-json{{"
    with pytest.raises(ThreadError) as exc_json:
        provider.complete(
            model="local-m",
            messages=[{"role": "user", "content": "hi"}],
            system=None,
            tools=None,
            max_tokens=64,
            request_meta={},
        )
    assert exc_json.value.error_code == "provider_invalid_json"

    # 3. Empty choices
    mock_openai_server.next_raw_body = json.dumps({"id": "c1", "choices": []})
    with pytest.raises(ThreadError) as exc_empty:
        provider.complete(
            model="local-m",
            messages=[{"role": "user", "content": "hi"}],
            system=None,
            tools=None,
            max_tokens=64,
            request_meta={},
        )
    assert exc_empty.value.error_code == "provider_empty_choices"


def test_end_to_end_multiturn_sqlite_and_verify_cli(
    tmp_path: Path,
    mock_openai_server: _MockOpenAIServer,
    capsys: pytest.CaptureFixture[str],
):
    db_path = tmp_path / "threads.db"
    store = SQLiteThreadStore(db_path)
    provider = get_provider(
        "openai_compat",
        base_url=mock_openai_server.base_url,
        api_key="local-key",
    )
    service = ThreadService(
        store=store,
        provider=provider,
        clock=FakeClock(1_700_000_000.0),
        provider_name="openai_compat",
    )

    try:
        # Turn 1: create thread
        turn1 = service.handle_messages(
            {
                "model": "qwen2.5-3b-instruct",
                "system": "Be helpful.",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "Turn one question"}],
                "thread": {"type": "create"},
            }
        )
        assert turn1["id"] == "chatcmpl_test_1"
        assert turn1["usage"] == {"input_tokens": 17, "output_tokens": 9}

        # Turn 2: continue thread
        turn2 = service.handle_messages(
            {
                "model": "qwen2.5-3b-instruct",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "Turn two follow-up"}],
                "thread": {"type": "continue", "previous_message_id": turn1["id"]},
            }
        )
        assert turn2["id"] == "chatcmpl_test_2"
        assert turn2["usage"] == {"input_tokens": 34, "output_tokens": 18}

        # Verify turn 2 sent full history (system + user1 + assistant1 + user2 = 4 messages)
        req2_msgs = mock_openai_server.requests[1]["body"]["messages"]
        assert len(req2_msgs) == 4
        assert [m["role"] for m in req2_msgs] == ["system", "user", "assistant", "user"]
        assert req2_msgs[2]["content"] == "reply-turn-1-msgs-2"
    finally:
        store.close()

    # Offline verification should succeed with exit code 0
    rc_valid = cli_main(["verify", "--db", str(db_path), "--thread-id", turn1["id"], "--json"])
    assert rc_valid == 0
    out_valid = json.loads(capsys.readouterr().out)
    assert out_valid["valid"] is True
    assert out_valid["turns_verified"] == 2
    assert out_valid["errors"] == []

    # Missing thread should fail with exit code 1
    rc_missing = cli_main(["verify", "--db", str(db_path), "--thread-id", "nonexistent_thread"])
    assert rc_missing == 1
    capsys.readouterr()

    # Tamper directly with turn 2's stored message history in SQLite
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT item_json FROM intent_threads WHERE response_id = ?",
        (turn2["id"],),
    ).fetchone()
    assert row is not None
    item = json.loads(row[0])
    item["messages"][0]["content"] = "TAMPERED USER PROMPT"
    conn.execute(
        "UPDATE intent_threads SET item_json = ? WHERE response_id = ?",
        (json.dumps(item), turn2["id"]),
    )
    conn.commit()
    conn.close()

    # Verification helper and CLI must detect tampering and exit 1
    res_tampered = verify_thread_db(db_path, turn1["id"])
    assert res_tampered.valid is False
    assert any("history digest mismatch" in e for e in res_tampered.errors)

    rc_tampered = cli_main(["verify", "--db", str(db_path), "--thread-id", turn1["id"]])
    assert rc_tampered == 1
