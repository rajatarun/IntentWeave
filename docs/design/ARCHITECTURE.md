# Architecture notes

See the [README architecture section](../README.md#how-it-works) for the overview. This document captures the DynamoDB item shape used in production deploys.

## DynamoDB schema

| Attribute | Type | Description |
| --- | --- | --- |
| `response_id` (PK) | S | Assistant message id for this turn |
| `thread_id` | S | Root thread id (first create response id) |
| `parent_response_id` | S | Previous response id continued from |
| `fingerprint_json` | M | Fixed fields from create + `history_digest` (see `intentweave.fingerprint`; v2 omits `model`) |
| `provider` | S | Backend adapter id for this turn (`INTENTWEAVE_PROVIDER`) |
| `model_policy` | S | `routed` or `pinned` (legacy items default to `pinned`) |
| `pinned_model` | S | Create-time model when policy is `pinned` |
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

Table encryption: SSE enabled (AWS-managed) in `template.yaml`. Use a customer-managed CMK in production if your policy requires it.
