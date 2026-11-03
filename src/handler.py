"""AWS Lambda entrypoint."""

from intentweave.api import lambda_handler as _route
from intentweave.clock import SystemClock
from intentweave.config import Settings
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

_service = ThreadService(
    _store,
    _provider,
    _clock,
    soft_ttl_seconds=_settings.soft_ttl_seconds,
    hard_ttl_seconds=_settings.hard_ttl_seconds,
)


def lambda_handler(event, context):
    return _route(event, context, _service)
