# IntentWeave architecture

Provider-agnostic message thread cache: Claude Message Threads–compatible **create** / **continue** with a DynamoDB (or in-memory) store and a pluggable `MessageProvider`.

## Request path

`API Gateway` → `handler.lambda_handler` → `ThreadService.handle_messages` → `ThreadStore` + `MessageProvider`.

## Thread fingerprint (v2)

The fingerprint is the set of **fixed** request fields that must stay consistent for every turn of a thread. It does **not** include `model` or provider identity—those may change per turn when `model_policy` is `routed`.

| Fingerprint field | On continue |
| --- | --- |
| `tool_choice`, `thinking`, `cache_control`, `feature_flags`, `fallbacks`, `output_config`, `context_management` | Must match create (400 `thread_fingerprint_mismatch`) |
| `history_digest` | Server-side only: SHA-256 of stored `system` + `messages`; detects tampered history (400 `thread_history_integrity_violation`) |
| `fingerprint_version` | `2` for new threads; absent/`1` = legacy |

### Legacy v1 fingerprints

Items written before multi-model routing may still have `model` (and optionally `provider`) inside `fingerprint_json`. Those threads are treated as **`model_policy: pinned`** until migrated. Legacy model pins are enforced on continue; other fingerprint fields still use normalized diffing (legacy `model` keys are ignored in field comparison).

Lazy migration: the first successful **routed** continue on a legacy thread drops `model`/`provider` from the stored fingerprint and bumps version.

## Model policy

Set on create only: `thread.model_policy` ∈ `{ "routed", "pinned" }` (default **`routed`** for new creates).

| Policy | Model on continue |
| --- | --- |
| `routed` | Any model (multi-provider routing) |
| `pinned` | Must match create model → 400 `thread_model_policy_violation` |

## Stored conversation shape

Each DynamoDB item is one assistant **response id**. `messages` is the merged transcript. Assistant entries include `model` and `provider` for the turn that produced them. Top-level `model` / `provider` on the item describe **this** response.

## TTL

Unchanged: soft TTL (`last_used_epoch` + `THREAD_SOFT_TTL_SECONDS`) and hard TTL (`ttl` attribute) for DynamoDB expiry.

See also `docs/design/ARCHITECTURE.md` for the DynamoDB attribute table.