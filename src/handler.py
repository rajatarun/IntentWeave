"""AWS Lambda entrypoint."""

from intentweave.api import lambda_handler as _route
from intentweave.clock import SystemClock
from intentweave.config import Settings
from intentweave.intent_labeler import IntentLabeler
from intentweave.providers.registry import get_provider
from intentweave.service import ThreadService
from intentweave.store.dynamodb import DynamoDBThreadStore
from intentweave.store.memory import MemoryThreadStore

_settings = Settings.from_environ()
_clock = SystemClock()
_provider = get_provider(_settings.provider)

if _settings.threads_table_name:
    _store = DynamoDBThreadStore(_settings.threads_table_name)
else:
    _store = MemoryThreadStore()

_intent_labeler = IntentLabeler(
    decisions_enabled=_settings.decisions_labeler_enabled,
    gemini_api_key=_settings.gemini_api_key,
    timeout_s=_settings.decisions_timeout_s,
    min_confidence=_settings.decisions_min_confidence,
)

_service = ThreadService(
    _store,
    _provider,
    _clock,
    soft_ttl_seconds=_settings.soft_ttl_seconds,
    hard_ttl_seconds=_settings.hard_ttl_seconds,
    provider_name=_settings.provider,
    intent_labeler=_intent_labeler,
)


def lambda_handler(event, context):
    return _route(event, context, _service)
