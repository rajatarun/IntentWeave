# IntentWeave

Provider-agnostic **message thread** service that mirrors [Anthropic Claude Message Threads](https://platform.claude.com/docs/en/build-with-claude/message-threads) semantics. IntentWeave stores short-lived server-side conversation turns so clients can send the full history once, then only new messages plus `previous_message_id` on later turns.

**Your application remains the source of truth.** Threads are a best-effort cache. On `thread_not_found` (404), replay the full conversation with `thread: { "type": "create" }`.

## Architecture

```text
Client ──► API Gateway HTTP API ──► Lambda (handler.py)
                                      │
                                      ├─ ThreadService (create / continue / fingerprint)
                                      ├─ ThreadStore (DynamoDB in AWS, in-memory if no table)
                                      └─ MessageProvider (mock default; optional adapters)
                                              │
                                              ▼
                                        DynamoDB (response_id PK, ttl attribute)
```

| Component | Role |
| --- | --- |
| `ThreadService` | Validates thread rules, merges stored messages, routes to provider |
| `ThreadStore` | One item per assistant **response id**; tracks `continued`, in-flight continue, TTL |
| `MessageProvider` | Pluggable LLM backend (`mock` for CI/local; `anthropic` / `bedrock` reserved) |

### DynamoDB schema

| Attribute | Type | Description |
| --- | --- | --- |
| `response_id` (PK) | S | Assistant message id for this turn |
| `thread_id` | S | Root thread id (first create response id) |
| `parent_response_id` | S | Previous response id continued from |
| `fingerprint_json` | M | Fixed fields from create (see below) |
| `system` | Any | Create-only system prompt |
| `tools` | Any | Create-only tools |
| `messages` | L | Full conversation including assistant turns |
| `model` | S | Model id |
| `stop_reason` | S | e.g. `end_turn`, `pause_turn`, `refusal` |
| `assistant_message` | M | Cached assistant payload |
| `continued` | BOOL | Whether this id was already continued |
| `continue_in_flight` | BOOL | Concurrent continue guard |
| `last_used_epoch` | N | Soft TTL anchor (default 300s) |
| `ttl` | N | DynamoDB TTL for hard delete (default 3600s) |
| `refused` / `paused` | BOOL | Refusal / pause_turn flags |

Table encryption: SSE enabled (AWS-managed). Follow your org CMK pattern for production if required (see ContextWeave / DeviceWeave).

## API

### `POST /v1/messages`

Claude-shaped request body with a top-level `thread` object.

**Create**

```bash
curl -sS "$API/v1/messages" \
  -H 'content-type: application/json' \
  -d '{
    "model": "claude-test-1",
    "max_tokens": 256,
    "cache_control": {"type": "ephemeral"},
    "system": "You are helpful.",
    "messages": [{"role": "user", "content": "Hello"}],
    "thread": {"type": "create"}
  }'
```

**Continue** (only new messages; do **not** send `system` or `tools`)

```bash
curl -sS "$API/v1/messages" \
  -H 'content-type: application/json' \
  -d '{
    "model": "claude-test-1",
    "max_tokens": 256,
    "cache_control": {"type": "ephemeral"},
    "messages": [{"role": "user", "content": "Follow up"}],
    "thread": {"type": "continue", "previous_message_id": "'"$MSG_ID"'"}
  }'
```

**`pause_turn` resume** — continue from the paused response id with an empty `messages` array:

```bash
curl -sS "$API/v1/messages" \
  -H 'content-type: application/json' \
  -d '{
    "model": "claude-test-1",
    "max_tokens": 256,
    "cache_control": {"type": "ephemeral"},
    "messages": [],
    "thread": {"type": "continue", "previous_message_id": "'"$PAUSED_ID"'"}
  }'
```

Do not send new user messages while the turn is paused.

### Thread rules (parity with Claude)

| Rule | Behavior |
| --- | --- |
| Create-only | `system`, `tools` only on create; present on continue → 400 |
| Fingerprint | `model`, `tool_choice`, `thinking`, `cache_control`, `feature_flags` (from `betas`), `fallbacks`, `output_config`, `context_management` must match create → 400 `thread_fingerprint_mismatch` |
| Append-only | Each response id continuable **once** → `thread_already_continued` |
| Concurrency | Second continue while first runs → `thread_continue_in_flight` |
| Missing / expired | 404 `thread_not_found` — **replay** with full history + new create |
| Refusal | Do not continue after `stop_reason: refusal` |
| Edits / branches | New create with full history (no in-place edit) |

IntentWeave does **not** require Anthropic beta headers on its own API. Map `betas` → `feature_flags` in the fingerprint when you want Claude parity.

### Error shape

```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "message": "...",
    "details": { "error_code": "thread_fingerprint_mismatch", "mismatched_fields": ["model"] }
  },
  "request_id": "req_..."
}
```

### `GET /health`

Liveness probe returning `{"status":"ok"}`.

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `THREADS_TABLE_NAME` | _(unset → in-memory store)_ | DynamoDB table name |
| `THREAD_SOFT_TTL_SECONDS` | `300` | Soft expiry after last successful store |
| `THREAD_HARD_TTL_SECONDS` | `3600` | DynamoDB TTL attribute horizon |
| `INTENTWEAVE_PROVIDER` | `mock` | `mock` (default), `anthropic`, `bedrock` (stubs) |
| `LOG_LEVEL` | `INFO` | Log level |

## Local development

```bash
make install
make test
make lint
make validate   # sam validate --lint
make sam-build
```

The **mock provider** echoes deterministic assistant text (no API keys). Test hooks in user text:

- `__intentweave_pause__` → `stop_reason: pause_turn`
- `__intentweave_refusal__` → `stop_reason: refusal`

## Deploy (SAM)

This repo ships `template.yaml` only; deploy from your AWS account:

```bash
sam build
sam deploy --guided
```

Parameters: `ThreadSoftTtlSeconds`, `ThreadHardTtlSeconds`, `IntentWeaveProvider`, `StackEnv`.

## Replay guidance

1. Keep full message history client-side (including tool results).
2. On 404 `thread_not_found`, send a new **create** with full `messages`, `system`, and `tools`.
3. Continue from the new response id.
4. On `thread_already_continued` or `thread_continue_in_flight`, replay if you never received the next response.

## Follow-ups

- Wire **mcp-observatory** quality gates for API contract tests.
- Implement optional **Anthropic Messages** and **Bedrock Converse** providers behind `INTENTWEAVE_PROVIDER`.
- Multi-tenant auth, billing, message batches, and on-demand compaction remain out of scope for v1.

## License

Apache-2.0 — see [LICENSE](LICENSE).
