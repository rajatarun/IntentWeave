"""Resolve Gemini API key from environment or AWS Secrets Manager (cached)."""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SECRET_NAME = "gemini/api_key"
DEFAULT_SECRET_REGION = "us-east-1"


def resolve_gemini_api_key(
    *,
    explicit_env_key: str | None = None,
    secret_name: str | None = None,
    secret_region: str | None = None,
    secrets_client: Any | None = None,
) -> str | None:
    """Return an API key from GEMINI_API_KEY or Secrets Manager; None if unavailable."""
    if explicit_env_key:
        return explicit_env_key

    name = secret_name or os.environ.get("GEMINI_SECRET_NAME") or DEFAULT_SECRET_NAME
    region = secret_region or os.environ.get("GEMINI_SECRET_REGION") or DEFAULT_SECRET_REGION

    if secrets_client is not None:
        return _fetch_secret(secrets_client, name, region)

    return _load_gemini_secret_cached(name, region)


def clear_gemini_api_key_cache() -> None:
    _load_gemini_secret_cached.cache_clear()


@lru_cache(maxsize=4)
def _load_gemini_secret_cached(secret_name: str, secret_region: str) -> str | None:
    import boto3

    client = boto3.client("secretsmanager", region_name=secret_region)
    return _fetch_secret(client, secret_name, secret_region)


def _fetch_secret(client: Any, secret_name: str, secret_region: str) -> str | None:
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except Exception:
        logger.exception(
            "gemini_secret_fetch_failed",
            extra={"secret_name": secret_name, "region": secret_region},
        )
        return None

    raw = response.get("SecretString")
    if raw is None:
        logger.warning(
            "gemini_secret_empty",
            extra={"secret_name": secret_name, "region": secret_region},
        )
        return None

    return _parse_secret_string(raw)


def _parse_secret_string(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None

    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(data, dict):
            for key in ("api_key", "GEMINI_API_KEY", "key"):
                value = data.get(key)
                if value:
                    return str(value).strip()
            return None

    return text
