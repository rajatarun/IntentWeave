# IntentWeave

**Keep multi-turn LLM requests small** by storing short-lived server-side message threads with Claude Message Threads–compatible semantics—while your app remains the source of truth.

**Who this is for:** Teams building on AWS (Lambda + HTTP API) who want create/continue thread behavior, replay guidance on expiry, and a pluggable LLM backend—without sending the full chat history on every turn.

> `[Demo GIF placeholder]` — screen recording of create → continue via `examples/local_thread_lifecycle.py` (contributions welcome).

## Quickstart (~5 minutes)

No AWS account needed for local try-out (mock provider + in-memory store).

```bash
git clone https://github.com/rajatarun/IntentWeave.git
cd IntentWeave
make install
export PATH="$HOME/.local/bin:$PATH"
make test
PYTHONPATH=src python3 examples/local_thread_lifecycle.py
```

You should see two assistant lines with `msg_…` ids and mock echo text.

More examples: [examples/README.md](examples/README.md).

### Deploy (requires AWS)

This repo ships a SAM template only; deploy in your account:

```bash
sam build
sam deploy --guided
```

Set `THREADS_TABLE_NAME` via the stack for durable threads. See [Environment variables](#environment-variables) and [docs/design/SECURITY_NOTES.md](docs/design/SECURITY_NOTES.md) before exposing a public endpoint.

For CI/CD production deploys, required GitHub **secrets** and **variables** are listed in [docs/DEPLOY_CONFIG.md](docs/DEPLOY_CONFIG.md).

## Core workflow (copy-paste)

These three patterns mirror production use: create, continue with new messages only, and resume after `pause_turn`.

### 1. Create thread

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

Save `id` from the response as `MSG_ID`.

### 2. Continue (new messages only)

Do **not** send `system` or `tools` on continue.

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

### 3. Resume after `pause_turn`

Continue from the paused response id with an **empty** `messages` array (no new user content while paused).

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

On `thread_not_found` (404), replay full history with a new **create**. See [Replay guidance](#replay-guidance).

## How it works

```text
Client ──► API Gateway HTTP API ──► Lambda (handler.py)
                                      │
                                      ├─ ThreadService (create / continue / fingerprint)
                                      ├─ ThreadStore (DynamoDB in AWS, in-memory if no table)
                                      └─ MessageProvider (mock default; anthropic/bedrock planned)
                                              │
                                              ▼
                                        DynamoDB (response_id PK, ttl attribute)
```

| Component | Role |
| --- | --- |
| `ThreadService` | Validates thread rules, merges stored messages, routes to provider |
| `ThreadStore` | One item per assistant **response id**; tracks `continued`, in-flight continue, TTL |
| `MessageProvider` | Pluggable LLM backend (`mock` for CI/local; other adapters via `INTENTWEAVE_PROVIDER`) |

Extension points: [docs/EXTENDING.md](docs/EXTENDING.md). Integration ideas: [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).

## Thread rules (parity with Claude)

| Rule | Behavior |
| --- | --- |
| Create-only | `system`, `tools` only on create; present on continue → 400 |
| Fingerprint | `model`, `tool_choice`, `thinking`, `cache_control`, `feature_flags` (from `betas`), `fallbacks`, `output_config`, `context_management` must match create → 400 `thread_fingerprint_mismatch` |
| Append-only | Each response id continuable **once** → `thread_already_continued` |
| Concurrency | Second continue while first runs → `thread_continue_in_flight` |
| Missing / expired | 404 `thread_not_found` — **replay** with full history + new create |
| Refusal | Do not continue after `stop_reason: refusal` |
| Edits / branches | New create with full history (no in-place edit) |

## API reference

### `POST /v1/messages`

Claude-shaped JSON body with a top-level `thread` object (`create` or `continue`).

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

Returns `{"status":"ok"}`.

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `THREADS_TABLE_NAME` | _(unset → in-memory store)_ | DynamoDB table name |
| `THREAD_SOFT_TTL_SECONDS` | `300` | Soft expiry after last successful store |
| `THREAD_HARD_TTL_SECONDS` | `3600` | DynamoDB TTL attribute horizon |
| `INTENTWEAVE_PROVIDER` | `mock` | `mock` (default); `anthropic` / `bedrock` reserved (not implemented) |
| `LOG_LEVEL` | `INFO` | Log level |

## Local development

```bash
make install
make test
make lint
make validate   # sam validate --lint (requires SAM CLI)
make sam-build
```

**Mock provider** echoes deterministic assistant text (no API keys). Test hooks in user content:

- `__intentweave_pause__` → `stop_reason: pause_turn`
- `__intentweave_refusal__` → `stop_reason: refusal`

## Replay guidance

1. Keep full message history client-side (including tool results).
2. On 404 `thread_not_found`, send a new **create** with full `messages`, `system`, and `tools`.
3. Continue from the new response id.
4. On `thread_already_continued` or `thread_continue_in_flight`, replay if you never received the next response.

## Documentation map

| Doc | Purpose |
| --- | --- |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, tests, PR process |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting |
| [docs/design/SECURITY_NOTES.md](docs/design/SECURITY_NOTES.md) | Threat model and deployment hardening |
| [docs/GOOD_FIRST_ISSUES.md](docs/GOOD_FIRST_ISSUES.md) | Starter tasks for new contributors |
| [docs/LAUNCH.md](docs/LAUNCH.md) | Draft launch post (not published) |

## Roadmap (high level)

- Implement **Anthropic Messages** and **Bedrock Converse** providers behind `INTENTWEAVE_PROVIDER`.
- API contract tests and optional observability (OpenTelemetry).
- Multi-tenant auth, billing, message batches, and on-demand compaction remain **out of scope for v1**.

## License

Apache-2.0 — see [LICENSE](LICENSE).
