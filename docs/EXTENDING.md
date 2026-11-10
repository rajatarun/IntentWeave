# Extending IntentWeave

IntentWeave is designed around two extension points: **message providers** (who generates assistant replies) and **thread stores** (where conversation state lives).

## Message providers

Implement the `MessageProvider` protocol in `src/intentweave/providers/base.py`:

```python
class MessageProvider(Protocol):
    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        system: Any | None,
        tools: Any | None,
        max_tokens: int,
        request_meta: dict[str, Any],
    ) -> ProviderResult: ...
```

Steps:

1. Add `src/intentweave/providers/your_provider.py` returning `ProviderResult` (`response_id`, `content`, `stop_reason`, etc.).
2. Register it in `src/intentweave/providers/registry.py` under a new `INTENTWEAVE_PROVIDER` value.
3. Add unit tests with deterministic fixtures (no live API calls in CI).

`request_meta` includes `{"thread": "create" | None}` so providers can adjust behavior per turn.

The built-in **mock provider** (`mock.py`) is the reference implementation: deterministic text, pause/refusal test hooks in user content.

## Thread stores

Implement `ThreadStore` in `src/intentweave/store/base.py`:

- `put(record: ThreadRecord) -> None`
- `get(response_id: str) -> ThreadRecord | None`
- `mark_continue_in_flight` / `clear_continue_in_flight` / `mark_continued` for concurrency rules

Existing implementations:

| Store | Module | When to use |
| --- | --- | --- |
| In-memory | `store/memory.py` | Tests, local examples, Lambda without DynamoDB |
| DynamoDB | `store/dynamodb.py` | Production SAM deploy |

To add Redis or another backend, mirror the DynamoDB conditional-update patterns used for `continue_in_flight` and `continued`.

## Wiring a custom store in Lambda

`handler.py` chooses the store from `THREADS_TABLE_NAME`. For experiments, you can import `ThreadService` directly (see `examples/`) or fork `handler.py` to instantiate your store.

## HTTP API

Routing lives in `src/intentweave/api.py`. New routes should remain thin: parse JSON, call `ThreadService`, map `ThreadError` to HTTP status.

Path normalization for API Gateway stage prefixes is handled in `_normalize_path()` — reuse it for new endpoints.

## Configuration

`Settings` in `src/intentweave/config.py` reads environment variables. Add new settings there and document them in the README environment table.
