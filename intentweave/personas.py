from __future__ import annotations

import re
from typing import Final

PERSONAS: Final[list[str]] = [
    "GEN_Z",
    "MILLENNIAL",
    "PROFESSIONAL",
    "EXECUTIVE",
    "MINIMAL",
]

# Each entry is (pattern, replacement) applied in order via re.sub.
# PROFESSIONAL is the neutral baseline; no substitutions needed.
_SUBSTITUTION_RULES: dict[str, list[tuple[str, str]]] = {
    "GEN_Z": [
        (r"Please provide the following information", "drop these deets"),
        (r"Please provide\b", "drop"),
        (r"\bthe following information\b", "these deets"),
        (r"\bhas been submitted successfully\b", "just went thru no cap"),
        (r"\bhas been submitted\b", "is submitted fr"),
        (r"\bYour request\b", "ur request"),
        (r"\bhas been blocked\b", "got lowkey blocked"),
        (r"\bcannot be processed\b", "can't rn"),
        (r"\bHere is\b", "check it,"),
        (r"\binformation\b", "info"),
        (r"\bInformation\b", "Info"),
        (r"\bThank you\b", "thx"),
        (r"\bplease\b", "pls"),
        (r"\bRequired\b", "Needed"),
        (r"\bsuccessfully\b", "no cap"),
    ],
    "MILLENNIAL": [
        (r"^Please provide the following information", "Hey! Just need a few more details"),
        (r"^Please provide\b", "Hey! Just need"),
        (r"\bhas been submitted successfully\b", "is all set"),
        (r"\bhas been blocked\b", "unfortunately can't go through"),
        (r"\bcannot be processed\b", "can't be processed right now"),
        (r"\bHere is\b", "Here's"),
        (r"\bThank you\b", "Thanks"),
    ],
    "PROFESSIONAL": [],
    "EXECUTIVE": [
        (r"Please provide the following information:\s*", "Required: "),
        (r"Please provide\b", "Required:"),
        (r"\bhas been submitted successfully\b", "Submitted."),
        (r"\bhas been submitted\b", "Submitted."),
        (r"\bYour request has been blocked:\s*", "Rejected: "),
        (r"\bYour request cannot be processed\b", "Request rejected"),
        (r"\bHere is the result for your \w+\b", "Result"),
        (r"\bHere is\b", "Result:"),
        (r"Thank you for your \w+\.\s*", ""),
    ],
    "MINIMAL": [
        (r"Please provide the following information:\s*", "Need: "),
        (r"Please provide\b", "Need:"),
        (r"\bhas been submitted successfully\b", "Done."),
        (r"\bhas been submitted\b", "Submitted."),
        (r"\bYour request has been blocked:\s*", "Blocked: "),
        (r"\bYour request cannot be processed\b", "Rejected."),
        (r"\bHere is the result for your \w+\b", "Result:"),
        (r"\bHere is\b", "Result:"),
        (r"Thank you for your \w+\.\s*", ""),
        (r"\bplease\b\.?\s*", ""),
        (r"\s{2,}", " "),
    ],
}

_SUFFIXES: dict[str, str] = {
    "GEN_Z": " ngl",
    "MILLENNIAL": "",
    "PROFESSIONAL": "",
    "EXECUTIVE": "",
    "MINIMAL": "",
}


def transform(message: str, persona: str) -> str:
    """Apply persona-based transformation to the output message only."""
    if persona not in PERSONAS:
        raise ValueError(f"Invalid persona {persona!r}. Must be one of {PERSONAS}")

    result = message
    for pattern, replacement in _SUBSTITUTION_RULES[persona]:
        result = re.sub(pattern, replacement, result)

    suffix = _SUFFIXES[persona]
    if suffix and not result.endswith(suffix):
        result = result.rstrip(".!?") + suffix

    return result
