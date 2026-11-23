"""Zero-dependency OpenAI-compatible HTTP provider using Python stdlib urllib."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any

from intentweave.errors import ThreadError
from intentweave.models import ProviderResult

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT_S = 60.0

_FINISH_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "refusal",
}


class OpenAICompatProvider:
    """Provider targeting OpenAI-compatible ``POST /v1/chat/completions`` endpoints.

    Uses only Python stdlib ``urllib.request`` so core IntentWeave remains zero-dependency.
    Works with local ``llama.cpp``, Ollama, vLLM, xAI, Gemini OpenAI-compat, and OpenAI.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        raw_base = (
            base_url
            if base_url is not None
            else os.environ.get("INTENTWEAVE_OPENAI_BASE_URL", DEFAULT_BASE_URL)
        )
        self.base_url = raw_base.rstrip("/")
        self.api_key = (
            api_key if api_key is not None else os.environ.get("INTENTWEAVE_OPENAI_API_KEY", "")
        )
        self.default_model = (
            default_model
            if default_model is not None
            else os.environ.get("INTENTWEAVE_OPENAI_MODEL", "")
        )
        if timeout_s is not None:
            self.timeout_s = float(timeout_s)
        else:
            env_timeout = os.environ.get("INTENTWEAVE_OPENAI_TIMEOUT_S")
            self.timeout_s = float(env_timeout) if env_timeout else DEFAULT_TIMEOUT_S

    @property
    def endpoint_url(self) -> str:
        if self.base_url.endswith("/v1/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        system: Any | None,
        tools: Any | None,
        max_tokens: int,
        request_meta: dict[str, Any],
    ) -> ProviderResult:
        del request_meta
        resolved_model = model or self.default_model
        if not resolved_model:
            raise ThreadError(
                http_status=400,
                error_type="invalid_request_error",
                message="A model ID is required for OpenAICompatProvider.",
                error_code="provider_missing_model",
            )

        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": _build_openai_messages(system=system, messages=messages),
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            self.endpoint_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw_body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = str(exc.reason)
            raise ThreadError(
                http_status=502,
                error_type="provider_error",
                message=f"OpenAI-compatible endpoint returned HTTP {exc.code}: {err_body}",
                error_code="provider_http_error",
                details={"upstream_status": exc.code, "upstream_body": err_body},
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ThreadError(
                http_status=502,
                error_type="provider_error",
                message=f"Failed to reach OpenAI-compatible endpoint: {exc}",
                error_code="provider_connection_error",
            ) from exc

        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ThreadError(
                http_status=502,
                error_type="provider_error",
                message="OpenAI-compatible endpoint returned invalid JSON.",
                error_code="provider_invalid_json",
            ) from exc

        return _parse_openai_response(data, fallback_model=resolved_model)


def _flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif "text" in block:
                    parts.append(str(block["text"]))
        return "\n".join(parts)
    return str(content)


def _build_openai_messages(
    *, system: Any | None, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system is not None:
        system_text = _flatten_content(system)
        if system_text:
            out.append({"role": "system", "content": system_text})
    for msg in messages:
        role = str(msg.get("role", "user"))
        content = _flatten_content(msg.get("content"))
        out.append({"role": role, "content": content})
    return out


def _parse_openai_response(data: dict[str, Any], *, fallback_model: str) -> ProviderResult:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ThreadError(
            http_status=502,
            error_type="provider_error",
            message="OpenAI-compatible response contained no choices.",
            error_code="provider_empty_choices",
        )

    first = choices[0]
    message = first.get("message") or {}
    text = message.get("content")
    content_blocks: list[dict[str, Any]] = []
    if text is not None:
        content_blocks.append({"type": "text", "text": str(text)})

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if isinstance(tc, dict):
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments", "{}")
                try:
                    parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    parsed_args = {"raw": raw_args}
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id") or f"toolu_{uuid.uuid4().hex}",
                        "name": fn.get("name", ""),
                        "input": parsed_args,
                    }
                )

    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})

    raw_finish = str(first.get("finish_reason") or "stop")
    stop_reason = _FINISH_REASON_MAP.get(raw_finish, raw_finish)

    raw_usage = data.get("usage") or {}
    input_tokens = int(raw_usage.get("prompt_tokens", raw_usage.get("input_tokens", 0)) or 0)
    output_tokens = int(raw_usage.get("completion_tokens", raw_usage.get("output_tokens", 0)) or 0)

    response_id = str(data.get("id") or f"msg_{uuid.uuid4().hex}")
    model_id = str(data.get("model") or fallback_model)

    return ProviderResult(
        response_id=response_id,
        model=model_id,
        content=content_blocks,
        stop_reason=stop_reason,
        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
    )
