import uuid
from typing import Any

from intentweave.models import ProviderResult

# Magic substrings in the last user text block for deterministic test behavior.
_PAUSE_MARKER = "__intentweave_pause__"
_REFUSAL_MARKER = "__intentweave_refusal__"


class MockProvider:
    """Deterministic provider for CI and local dev (no API keys)."""

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
        del system, tools, max_tokens
        if request_meta.get("resume_pause"):
            return ProviderResult(
                response_id=f"msg_{uuid.uuid4().hex}",
                model=model,
                content=[{"type": "text", "text": f"mock:{model}:resumed"}],
                stop_reason="end_turn",
                usage={"input_tokens": 10, "output_tokens": 5},
            )

        last_user = _last_user_text(messages)
        stop_reason = "end_turn"
        text = f"mock:{model}:{len(messages)} turns"

        if last_user == _PAUSE_MARKER:
            stop_reason = "pause_turn"
            text = "mock:paused"
        elif last_user == _REFUSAL_MARKER:
            stop_reason = "refusal"
            text = "mock:refused"

        return ProviderResult(
            response_id=f"msg_{uuid.uuid4().hex}",
            model=model,
            content=[{"type": "text", "text": text}],
            stop_reason=stop_reason,
            usage={"input_tokens": 10, "output_tokens": 5},
        )


def _last_user_text(messages: list[dict[str, Any]]) -> str | None:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in reversed(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    return str(block.get("text", ""))
    return None
