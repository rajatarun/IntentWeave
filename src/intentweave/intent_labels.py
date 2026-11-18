"""Fixed vocabulary for thread intent labeling."""

from __future__ import annotations

from typing import Any

INTENT_LABELS: tuple[str, ...] = (
    "task",
    "question",
    "creative",
    "tool_use",
    "small_talk",
    "continuation",
    "other",
)

INTENT_CHOICE_CRITERIA: dict[str, str] = {
    "task": "The user wants something done: edit, fix, build, run, schedule, or complete work.",
    "question": "The user seeks factual information, an explanation, or a direct answer.",
    "creative": "The user wants brainstorming, writing, rewriting, or open-ended generation.",
    "tool_use": "The user is asking to use tools, APIs, code execution, or structured tool output.",
    "small_talk": "Greeting, thanks, chit-chat, or social filler without a substantive task.",
    "continuation": "Resume, continue, or clarify the prior turn without new substantive content.",
    "other": "Does not clearly fit the other categories.",
}


def choices_criteria() -> dict[str, str]:
    return {k: v for k, v in INTENT_CHOICE_CRITERIA.items() if k != "small_talk"}


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                parts.append(block["content"])
        return "\n".join(parts).strip()
    return ""


def latest_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            text = message_text(msg.get("content"))
            if text:
                return text
    return ""
