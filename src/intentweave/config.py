import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    """Runtime configuration from environment variables."""

    threads_table_name: str | None
    soft_ttl_seconds: int
    hard_ttl_seconds: int
    provider: str
    log_level: str

    @classmethod
    def from_environ(cls) -> "Settings":
        return cls(
            threads_table_name=os.environ.get("THREADS_TABLE_NAME") or None,
            soft_ttl_seconds=_int_env("THREAD_SOFT_TTL_SECONDS", 300),
            hard_ttl_seconds=_int_env("THREAD_HARD_TTL_SECONDS", 3600),
            provider=(os.environ.get("INTENTWEAVE_PROVIDER") or "mock").lower(),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
