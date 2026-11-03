from typing import Any, Protocol

from intentweave.models import ProviderResult


class MessageProvider(Protocol):
    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        system: Any | None,
        tools: Any | None,
        max_tokens: int,
        request_meta: dict[str, Any],
    ) -> ProviderResult: ...
