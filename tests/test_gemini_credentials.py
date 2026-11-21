import json
from unittest.mock import MagicMock

import pytest

from intentweave.gemini_credentials import (
    clear_gemini_api_key_cache,
    resolve_gemini_api_key,
)


@pytest.fixture(autouse=True)
def _clear_secret_cache():
    clear_gemini_api_key_cache()
    yield
    clear_gemini_api_key_cache()


def test_prefers_explicit_env_key_over_secrets():
    client = MagicMock()
    key = resolve_gemini_api_key(explicit_env_key="from-env", secrets_client=client)
    assert key == "from-env"
    client.get_secret_value.assert_not_called()


def test_loads_plain_string_secret():
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": "gemini-key-plain"}

    key = resolve_gemini_api_key(
        secret_name="gemini/api_key",
        secret_region="us-east-1",
        secrets_client=client,
    )

    assert key == "gemini-key-plain"
    client.get_secret_value.assert_called_once_with(SecretId="gemini/api_key")


def test_loads_json_secret_with_api_key_field():
    client = MagicMock()
    client.get_secret_value.return_value = {
        "SecretString": json.dumps({"api_key": "json-key"}),
    }

    key = resolve_gemini_api_key(
        secret_name="gemini/api_key",
        secret_region="us-east-1",
        secrets_client=client,
    )

    assert key == "json-key"


def test_secret_fetch_failure_returns_none():
    client = MagicMock()
    client.get_secret_value.side_effect = RuntimeError("access denied")

    key = resolve_gemini_api_key(
        secret_name="gemini/api_key",
        secret_region="us-east-1",
        secrets_client=client,
    )

    assert key is None


def test_secret_cache_avoids_duplicate_calls(monkeypatch):
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": "cached-key"}

    factory = MagicMock(return_value=client)
    monkeypatch.setattr("boto3.client", factory)

    first = resolve_gemini_api_key(
        secret_name="gemini/api_key",
        secret_region="us-east-1",
    )
    second = resolve_gemini_api_key(
        secret_name="gemini/api_key",
        secret_region="us-east-1",
    )

    assert first == second == "cached-key"
    client.get_secret_value.assert_called_once()
