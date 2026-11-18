"""Rule-based intent labeler (default and fallback)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from intentweave.intent_labels import latest_user_text

_SMALL_TALK_RE = re.compile(
    r"^(hi|hello|hey|thanks|thank you|good morning|good afternoon|good evening|"
    r"how are you|what's up|whats up|bye|goodbye|see you|nice to meet you)[\s!?.]*$",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"^(who|what|when|where|why|how|which|is|are|do|does|did|can|could|would|will)\b",
    re.IGNORECASE,
)
_TOOL_RE = re.compile(
    r"\b(tool|function call|api|execute|run code|python|javascript|sql|query)\b",
    re.IGNORECASE,
)
_CREATIVE_RE = re.compile(
    r"\b(write|draft|brainstorm|story|poem|blog|essay|rewrite|improve this text)\b",
    re.IGNORECASE,
)
_CONTINUATION_RE = re.compile(
    r"^(continue|go on|keep going|resume|carry on|please proceed)[\s!?.]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IntentLabelResult:
    label: str
    source: str
    confidence: float


def label_heuristic(
    *,
    messages: list[dict[str, Any]],
    resume_pause: bool = False,
) -> IntentLabelResult:
    if resume_pause:
        return IntentLabelResult("continuation", "heuristic", 0.92)

    text = latest_user_text(messages)
    lowered = text.lower().strip()

    if not lowered:
        return IntentLabelResult("continuation", "heuristic", 0.75)

    if _SMALL_TALK_RE.match(lowered):
        return IntentLabelResult("small_talk", "heuristic", 0.88)

    if _CONTINUATION_RE.match(lowered):
        return IntentLabelResult("continuation", "heuristic", 0.86)

    if "?" in text and _QUESTION_RE.search(lowered):
        return IntentLabelResult("question", "heuristic", 0.72)

    if _TOOL_RE.search(lowered) or "```" in text:
        return IntentLabelResult("tool_use", "heuristic", 0.7)

    if _CREATIVE_RE.search(lowered):
        return IntentLabelResult("creative", "heuristic", 0.68)

    if any(word in lowered for word in ("please", "need you to", "help me", "can you")):
        return IntentLabelResult("task", "heuristic", 0.65)

    return IntentLabelResult("other", "heuristic", 0.55)
