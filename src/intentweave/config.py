import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _bool_env(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime configuration from environment variables."""

    threads_table_name: str | None
    soft_ttl_seconds: int
    hard_ttl_seconds: int
    provider: str
    log_level: str
    decisions_labeler_enabled: bool
    gemini_api_key: str | None
    gemini_secret_name: str
    gemini_secret_region: str
    decisions_min_confidence: float
    decisions_timeout_s: float

    @classmethod
    def from_environ(cls) -> "Settings":
        return cls(
            threads_table_name=os.environ.get("THREADS_TABLE_NAME") or None,
            soft_ttl_seconds=_int_env("THREAD_SOFT_TTL_SECONDS", 300),
            hard_ttl_seconds=_int_env("THREAD_HARD_TTL_SECONDS", 3600),
            provider=(os.environ.get("INTENTWEAVE_PROVIDER") or "mock").lower(),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            decisions_labeler_enabled=_bool_env("INTENTWEAVE_DECISIONS_LABELER", default=False),
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            gemini_secret_name=os.environ.get("GEMINI_SECRET_NAME") or "gemini/api_key",
            gemini_secret_region=os.environ.get("GEMINI_SECRET_REGION") or "us-east-1",
            decisions_min_confidence=_float_env("INTENTWEAVE_DECISIONS_MIN_CONFIDENCE", 0.5),
            decisions_timeout_s=_float_env("INTENTWEAVE_DECISIONS_TIMEOUT_S", 1.5),
        )
