# Integration opportunities

IntentWeave exposes a **Claude Messages–shaped HTTP API** with optional `thread` create/continue semantics. Below are ecosystems where an adapter or sidecar could fit, whether anything exists in this repo today, and rough effort.

## Summary (top opportunities)

| Integration | Fit | Implemented | Effort |
| --- | --- | --- | --- |
| Anthropic Messages API (provider) | **High** | Stub only (`INTENTWEAVE_PROVIDER=anthropic`) | Medium |
| AWS Bedrock Converse (provider) | **High** | Stub only | Medium |
| OpenTelemetry (Lambda traces + metrics) | **High** | No | Small–medium |
| LangChain / LangGraph (client proxy) | **Medium** | No | Medium |
| MCP tool servers | **Medium** | No | Medium |
| OpenAI Chat Completions shape | **Low** | No | Large (different thread model) |

---

## Anthropic Messages API

**Fit: High**

**What it is:** Run IntentWeave as a thread-aware proxy in front of the real Anthropic Messages API.

**Adapter shape:**

- Implement `MessageProvider` in `src/intentweave/providers/anthropic.py` using the official SDK or HTTP client.
- Map stored thread history + new messages to a single Messages API call on continue.
- Honor fingerprint fields already extracted in `intentweave.fingerprint`.

**Effort:** ~2–5 days for create/continue, error mapping, and integration tests with recorded fixtures.

**Status:** `get_provider("anthropic")` raises `NotImplementedError` today.

---

## AWS Bedrock Converse

**Fit: High**

**Adapter shape:**

- `MessageProvider` implementation calling `bedrock-runtime` Converse API.
- Reuse SAM IAM policies (extend `template.yaml` for `bedrock:InvokeModel`).

**Effort:** Similar to Anthropic; plus model-id mapping and regional endpoints.

**Status:** Stub only.

---

## Amazon Bedrock AgentCore / custom agents

**Fit: Medium**

Agents that already call Claude-shaped APIs could point their base URL at IntentWeave to shrink request payloads on multi-turn tool loops. AgentCore-specific hooks are not required for a minimal HTTP integration.

**Adapter shape:** Configuration-only (endpoint URL + thread headers/body). Optional: AgentCore observability export alongside OTel.

**Effort:** Small for HTTP; larger if you need AgentCore identity or memory plugins.

**Status:** Not implemented.

---

## OpenTelemetry

**Fit: High**

**Adapter shape:**

- Wrap `lambda_handler` and `ThreadService.handle_messages` with spans (`thread.type`, `response_id`, error codes).
- Export via Lambda ADOT layer or OTEL_* env vars (no change to thread semantics).

**Effort:** ~1–2 days.

**Status:** Not implemented.

---

## LangChain / LangGraph

**Fit: Medium**

**Adapter shape:**

- LangChain `BaseChatModel` or custom HTTP client that sends `thread: { type, previous_message_id }` on each turn.
- On `thread_not_found`, replay full history with a new create (documented client pattern).

**Effort:** ~3–5 days for a maintained community package; smaller for an internal wrapper.

**Status:** Not implemented.

---

## MCP (Model Context Protocol)

**Fit: Medium**

MCP hosts often maintain conversation state locally. IntentWeave could back **server-side thread storage** for MCP clients that speak HTTP, or expose thread metadata as MCP resources (read-only thread snapshot).

**Adapter shape:** Thin MCP server that forwards to `POST /v1/messages` or embeds `ThreadService` in-process.

**Effort:** ~1 week for a reference MCP server with create/continue tools.

**Status:** Not implemented.

---

## API contract testing (e.g. mcp-observatory-style gates)

**Fit: Medium**

README mentions future quality gates for the HTTP contract. Fit is **medium** because it is CI/tooling, not runtime.

**Adapter shape:** OpenAPI or recorded fixtures against `/v1/messages` and error shapes.

**Effort:** Small once OpenAPI is published.

**Status:** Planned (noted in README follow-ups).

---

## Other SDKs (OpenAI, Google, etc.)

**Fit: Low** for first-class support — thread fingerprint rules mirror Anthropic Message Threads. A generic adapter would need explicit mapping layers or a reduced feature set.

**Status:** Not planned in v1.
