import json
from typing import Any

# Fields that must match on every turn of a thread (Claude "fixed" group, provider-agnostic).
FINGERPRINT_KEYS = (
    "model",
    "tool_choice",
    "thinking",
    "cache_control",
    "feature_flags",
    "fallbacks",
    "output_config",
    "context_management",
)


def extract_fingerprint(body: dict[str, Any]) -> dict[str, Any]:
    """Build the canonical fingerprint payload from a request body."""
    fp: dict[str, Any] = {}
    for key in FINGERPRINT_KEYS:
        if key in body:
            fp[key] = body[key]
    # Normalize feature_flags from anthropic-style betas header mapping in body.
    if "betas" in body and "feature_flags" not in fp:
        fp["feature_flags"] = sorted(body["betas"]) if body["betas"] else []
    return fp


def fingerprint_digest(fp: dict[str, Any]) -> str:
    return json.dumps(fp, sort_keys=True, separators=(",", ":"))


def diff_fingerprints(stored: dict[str, Any], incoming: dict[str, Any]) -> list[str]:
    mismatched: list[str] = []
    keys = set(stored) | set(incoming)
    for key in sorted(keys):
        if stored.get(key) != incoming.get(key):
            mismatched.append(key)
    return mismatched
