# Security notes (v1)

IntentWeave is a **short-lived server-side thread cache** for Claude-shaped message APIs. It is not a full chat platform, identity system, or secrets vault.

## Threat model (summary)

| Asset | Risk | Mitigation today | Gaps |
| --- | --- | --- | --- |
| Conversation turns in DynamoDB | Confidentiality | SSE on table (AWS-managed key in SAM template) | No CMK, no field-level encryption |
| HTTP API | Unauthorized use | **None by default** — API is open if URL is known | Add API Gateway authorizers, WAF, or private API |
| Thread ids | Guessing / enumeration | Opaque `msg_*` ids | Rate limiting not implemented |
| Provider credentials | Leak via Lambda env | Not used when `INTENTWEAVE_PROVIDER=mock` | Future Anthropic/Bedrock adapters need Secrets Manager |
| TTL expiry | Stale data retention | Soft + hard TTL | Clients must replay on 404 |

## Trust boundaries

```text
[Client app] ──HTTPS──► [API Gateway] ──► [Lambda: ThreadService]
                                              │
                                              ├─► DynamoDB (thread rows)
                                              └─► MessageProvider (mock or future LLM API)
```

- **Your application** remains the source of truth for full history. Threads are best-effort.
- **Lambda** can read and write all stored messages for a thread id it knows.
- **Mock provider** never calls the network; suitable for local dev and CI.

## Deployment hardening (recommended)

1. Restrict `POST /v1/messages` with JWT, IAM, or API keys at API Gateway.
2. Use a customer-managed KMS key for DynamoDB if your policy requires it.
3. Store LLM API keys in AWS Secrets Manager when non-mock providers are enabled.
4. Enable CloudWatch logging; avoid logging full message bodies in production.
5. Set sensible `THREAD_SOFT_TTL_SECONDS` / `THREAD_HARD_TTL_SECONDS` for your compliance window.

## Local / no-cloud usage

Unit tests, examples, and development can run entirely on the **in-memory store** with the **mock provider** (no `THREADS_TABLE_NAME`, no AWS credentials). Deployed operation requires AWS for Lambda, API Gateway, and optionally DynamoDB.
