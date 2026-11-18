"""Gemini Decisions API intent labeler (opt-in)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any, Protocol

from intentweave.intent_heuristic import IntentLabelResult, label_heuristic
from intentweave.intent_labels import INTENT_LABELS, choices_criteria

logger = logging.getLogger(__name__)

DECISIONS_MODEL = "gemini-decision-1"
DEFAULT_TIMEOUT_S = 1.5
DEFAULT_MIN_CONFIDENCE = 0.5
_SMALL_TALK_NOUL_THRESHOLD = 0.85


class DecisionsClient(Protocol):
    def create(self, *, model: str, input: str, questions: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class DecisionsLabelerConfig:
    api_key: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    min_confidence: float = DEFAULT_MIN_CONFIDENCE


def _build_questions() -> dict[str, Any]:
    return {
        "intent": {
            "type": "choice",
            "instructions": "Which intent label best describes the latest user turn?",
            "criteria": choices_criteria(),
        },
        "is_small_talk": {
            "type": "noul",
            "instructions": "Is this latest user turn primarily small talk?",
            "criteria": {
                "true_description": (
                    "Greeting, thanks, social chat, or filler without a substantive request."
                ),
                "false_description": (
                    "The user is asking for work, information, tools, or creative output."
                ),
            },
        },
    }


def _answer_dict(result: Any, key: str) -> dict[str, Any] | None:
    answers = getattr(result, "answers", None)
    if answers is None and isinstance(result, dict):
        answers = result.get("answers")
    if not answers:
        return None
    if isinstance(answers, dict):
        answer = answers.get(key)
    else:
        answer = answers.get(key)
    if answer is None:
        return None
    if isinstance(answer, dict):
        return answer
    return {
        "type": getattr(answer, "type", None),
        "choice": getattr(answer, "choice", None),
        "noul": getattr(answer, "noul", None),
        "confidence": getattr(answer, "confidence", None),
        "probabilities": getattr(answer, "probabilities", None),
    }


def parse_decisions_response(result: Any, *, min_confidence: float) -> IntentLabelResult | None:
    small = _answer_dict(result, "is_small_talk")
    choice = _answer_dict(result, "intent")

    if small is None or choice is None:
        return None

    try:
        st_conf = float(small.get("confidence"))
        st_noul = float(small.get("noul"))
        ch_conf = float(choice.get("confidence"))
        picked = str(choice.get("choice") or "").strip()
    except (TypeError, ValueError):
        return None

    if st_noul >= _SMALL_TALK_NOUL_THRESHOLD and st_conf >= min_confidence:
        return IntentLabelResult("small_talk", "gemini_decisions", st_conf)

    if not picked or picked not in INTENT_LABELS:
        return None

    if ch_conf < min_confidence:
        return None

    return IntentLabelResult(picked, "gemini_decisions", ch_conf)


def label_with_decisions(
    *,
    messages: list[dict[str, Any]],
    resume_pause: bool,
    client: DecisionsClient,
    config: DecisionsLabelerConfig,
) -> IntentLabelResult:
    from intentweave.intent_labels import latest_user_text

    text = latest_user_text(messages)
    if resume_pause and not text:
        return label_heuristic(messages=messages, resume_pause=True)

    if not text:
        fallback = label_heuristic(messages=messages, resume_pause=resume_pause)
        return IntentLabelResult(fallback.label, "gemini_decisions_fallback", fallback.confidence)

    questions = _build_questions()

    def _call() -> Any:
        return client.create(model=DECISIONS_MODEL, input=text, questions=questions)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            raw = future.result(timeout=config.timeout_s)
    except FuturesTimeoutError:
        logger.info("intent_decisions_timeout")
        fallback = label_heuristic(messages=messages, resume_pause=resume_pause)
        return IntentLabelResult(fallback.label, "gemini_decisions_fallback", fallback.confidence)
    except Exception:
        logger.exception("intent_decisions_error")
        fallback = label_heuristic(messages=messages, resume_pause=resume_pause)
        return IntentLabelResult(fallback.label, "gemini_decisions_fallback", fallback.confidence)

    parsed = parse_decisions_response(raw, min_confidence=config.min_confidence)
    if parsed is None:
        fallback = label_heuristic(messages=messages, resume_pause=resume_pause)
        return IntentLabelResult(fallback.label, "gemini_decisions_fallback", fallback.confidence)
    return parsed


def build_genai_client(api_key: str) -> DecisionsClient:
    from google import genai

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})

    class _Adapter:
        def create(self, *, model: str, input: str, questions: dict[str, Any]) -> Any:
            return client.decisions.create(model=model, input=input, questions=questions)

    return _Adapter()
