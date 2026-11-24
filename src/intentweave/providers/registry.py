import os
from typing import Any

from intentweave.providers.base import MessageProvider
from intentweave.providers.mock import MockProvider
from intentweave.providers.openai_compat import OpenAICompatProvider


def get_provider(name: str | None = None, **kwargs: Any) -> MessageProvider:
    chosen = (name or os.environ.get("INTENTWEAVE_PROVIDER") or "mock").lower()
    if chosen == "mock":
        return MockProvider()
    if chosen in ("openai_compat", "openai-compat"):
        return OpenAICompatProvider(**kwargs)
    if chosen in ("anthropic", "bedrock"):
        raise NotImplementedError(
            f"Provider '{chosen}' is not enabled in this build. "
            "Set INTENTWEAVE_PROVIDER=mock or openai_compat, "
            "or implement the adapter behind env flags."
        )
    raise ValueError(f"Unknown provider: {chosen}")
