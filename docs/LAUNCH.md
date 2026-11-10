# Launch draft (not published)

Use this as a starting point for a blog post, README announcement, or community post. Edit before publishing.

---

## Draft post

### Title (working)

**IntentWeave: server-side message threads for your Claude-shaped APIs**

### Problem

Multi-turn LLM apps repeat the full conversation on every request. Anthropic's Message Threads let clients send history once, then only new turns—but that behavior is tied to their hosted API.

### Why it matters

If you run agents on AWS (Lambda, private networking, your own compliance boundary), you still want **smaller payloads**, **consistent thread rules**, and **clear replay semantics** when a thread expires—without forking your client SDK.

### What IntentWeave does

- HTTP **`POST /v1/messages`** with `thread: { "type": "create" | "continue" }`.
- **Provider-agnostic** core: mock provider for local dev; hooks for Anthropic/Bedrock adapters.
- **Pluggable store**: in-memory for tests, DynamoDB in SAM deploy.
- **Claude-aligned rules**: fingerprint matching, single continue per response id, pause/refusal handling.

### Honest limits (v1)

- **No authentication** on the API by default—you must add API Gateway authorizers.
- **Anthropic and Bedrock providers are stubs**; production LLM calls require implementing `MessageProvider`.
- **Short TTL cache**, not durable chat history—your app must retain full history and replay on `thread_not_found`.
- **AWS required** for the packaged serverless deploy; local library use does not need AWS.

### Try it

```bash
git clone https://github.com/rajatarun/IntentWeave.git
cd IntentWeave
make install && make test
PYTHONPATH=src python3 examples/local_thread_lifecycle.py
```

Deploy with SAM when you have an AWS account (`sam build && sam deploy --guided`).

### License

Apache-2.0.

---

## Communities where this fits

| Community | Angle |
| --- | --- |
| Anthropic Discord / forums | Thread parity, self-hosted edge cases |
| AWS builders (re:Post, local meetups) | Lambda + DynamoDB pattern |
| LangChain / LangGraph discussions | Client adapter for thread continuation |
| r/LocalLLaMA / self-hosted AI | Architecture reference (with mock provider) |
| OpenTelemetry / observability | Future tracing for thread lifecycles |

---

## Pre-launch checklist

- [ ] Owner reviews SECURITY.md and SAM defaults
- [ ] Decide on first provider to implement beyond mock
- [ ] Add demo GIF or short screen recording to README (placeholder today)
- [ ] Tag v0.1.0 after API stabilizes
