import os

from intentweave.providers.base import MessageProvider
from intentweave.providers.mock import MockProvider


def get_provider(name: str | None = None) -> MessageProvider:
    chosen = (name or os.environ.get("INTENTWEAVE_PROVIDER") or "mock").lower()
    if chosen == "mock":
        return MockProvider()
    if chosen in ("anthropic", "bedrock"):
        raise NotImplementedError(
            f"Provider '{chosen}' is not enabled in this build. "
            "Set INTENTWEAVE_PROVIDER=mock or implement the adapter behind env flags."
        )
    raise ValueError(f"Unknown provider: {chosen}")
