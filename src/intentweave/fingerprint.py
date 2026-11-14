import hashlib
import json
from typing import Any

# Current fingerprint schema (model/provider are not fixed across turns).
FINGERPRINT_VERSION = 2

# Fields that must match on every turn of a thread (Claude "fixed" group, minus routing).
FINGERPRINT_KEYS = (
    "tool_choice",
    "thinking",
    "cache_control",
    "feature_flags",
    "fallbacks",
    "output_config",
    "context_management",
)

# Legacy v1 fingerprints (before multi-model routing) also pinned `model`.
LEGACY_V1_EXTRA_KEYS = ("model", "provider")


def extract_fingerprint(body: dict[str, Any]) -> dict[str, Any]:
    """Build the canonical fingerprint payload from a request body."""
    fp: dict[str, Any] = {"fingerprint_version": FINGERPRINT_VERSION}
    for key in FINGERPRINT_KEYS:
        if key in body:
            fp[key] = body[key]
    # Normalize feature_flags from anthropic-style betas header mapping in body.
    if "betas" in body and "feature_flags" not in fp:
        fp["feature_flags"] = sorted(body["betas"]) if body["betas"] else []
    return fp


def attach_history_digest(
    fp: dict[str, Any], *, system: Any | None, messages: list[dict[str, Any]]
) -> dict[str, Any]:
    """Attach a digest of stored conversation state for tamper detection."""
    out = dict(fp)
    out["history_digest"] = history_digest(system=system, messages=messages)
    return out


def history_digest(*, system: Any | None, messages: list[dict[str, Any]]) -> str:
    payload = {"system": system, "messages": messages}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fingerprint_digest(fp: dict[str, Any]) -> str:
    return json.dumps(normalize_fingerprint(fp), sort_keys=True, separators=(",", ":"))


def normalize_fingerprint(fp: dict[str, Any]) -> dict[str, Any]:
    """Strip non-comparable and legacy routing keys for diffing."""
    allowed = set(FINGERPRINT_KEYS) | {"fingerprint_version", "history_digest"}
    return {k: fp[k] for k in sorted(fp) if k in allowed and k in fp}


def is_legacy_fingerprint(fp: dict[str, Any]) -> bool:
    version = fp.get("fingerprint_version")
    if version is None:
        return True
    try:
        return int(version) < FINGERPRINT_VERSION
    except (TypeError, ValueError):
        return True


def diff_fingerprints(stored: dict[str, Any], incoming: dict[str, Any]) -> list[str]:
    """Return sorted client-supplied fingerprint fields that differ from the stored thread."""
    mismatched: list[str] = []
    for key in FINGERPRINT_KEYS:
        if stored.get(key) != incoming.get(key):
            mismatched.append(key)
    if not is_legacy_fingerprint(stored):
        if stored.get("fingerprint_version") != incoming.get("fingerprint_version"):
            mismatched.append("fingerprint_version")
    return mismatched


def legacy_model_mismatch(
    stored: dict[str, Any], incoming_model: str, incoming_provider: str | None
) -> bool:
    """True when a legacy/pinned fingerprint pinned model (or provider) and the request differs."""
    if not is_legacy_fingerprint(stored):
        return False
    pinned_model = stored.get("model")
    if pinned_model is not None and pinned_model != incoming_model:
        return True
    pinned_provider = stored.get("provider")
    if (
        pinned_provider is not None
        and incoming_provider is not None
        and pinned_provider != incoming_provider
    ):
        return True
    return False


def verify_history_digest(
    record_fp: dict[str, Any], *, system: Any | None, messages: list[dict[str, Any]]
) -> bool:
    expected = record_fp.get("history_digest")
    if expected is None:
        return True
    return history_digest(system=system, messages=messages) == expected
