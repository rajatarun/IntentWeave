"""Orchestrates heuristic and optional Gemini Decisions intent labeling."""

from __future__ import annotations

from typing import Any

from intentweave.intent_decisions import (
    DecisionsClient,
    DecisionsLabelerConfig,
    build_genai_client,
    label_with_decisions,
)
from intentweave.intent_heuristic import IntentLabelResult, label_heuristic


class IntentLabeler:
    def __init__(
        self,
        *,
        decisions_enabled: bool = False,
        gemini_api_key: str | None = None,
        timeout_s: float = 1.5,
        min_confidence: float = 0.5,
        client: DecisionsClient | None = None,
    ) -> None:
        self._decisions_enabled = decisions_enabled
        self._config: DecisionsLabelerConfig | None = None
        self._client: DecisionsClient | None = client
        if decisions_enabled and gemini_api_key:
            self._config = DecisionsLabelerConfig(
                api_key=gemini_api_key,
                timeout_s=timeout_s,
                min_confidence=min_confidence,
            )
            if client is None:
                self._client = build_genai_client(gemini_api_key)

    @property
    def enabled(self) -> bool:
        return self._decisions_enabled

    def label_thread_turn(
        self,
        *,
        messages: list[dict[str, Any]],
        resume_pause: bool = False,
    ) -> IntentLabelResult | None:
        if not self._decisions_enabled:
            return None

        if self._config is not None and self._client is not None:
            return label_with_decisions(
                messages=messages,
                resume_pause=resume_pause,
                client=self._client,
                config=self._config,
            )

        return label_heuristic(messages=messages, resume_pause=resume_pause)
