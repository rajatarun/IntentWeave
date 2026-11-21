# Enabling Gemini Decisions labeling in production

The Gemini Decisions intent labeler is **off by default**. Production enables it only via a GitHub repository (or `prod` environment) variable — not by setting `WEAVE_DECISIONS_LIVE` or committing API keys.

## Prerequisites

1. Store the Gemini Developer API key in **AWS Secrets Manager** in `us-east-1` as secret name `gemini/api_key` (plain string or JSON with an `api_key` field).
2. Ensure the deploy completed at least once after this wiring so the messages Lambda has `secretsmanager:GetSecretValue` on `arn:aws:secretsmanager:us-east-1:<account>:secret:gemini/api_key-*`.

## Turn on

| Setting | Where | Value |
| --- | --- | --- |
| `INTENTWEAVE_DECISIONS_LABELER` | GitHub **variable** (repo or `prod` environment) | `1` |

Push to `main` or run **IntentWeave CI** via `workflow_dispatch`. The **Deploy prod (SAM)** job passes `IntentWeaveDecisionsLabeler` into the stack; Lambda receives `INTENTWEAVE_DECISIONS_LABELER=1`.

At cold start, the handler loads the key from Secrets Manager (`GEMINI_SECRET_NAME`, default `gemini/api_key`) with an in-process cache. If the secret is missing or unreadable, labeling falls back to the heuristic labeler while the flag remains on.

## Verify

After deploy, `POST /v1/messages` with `thread.type` `create` or `continue` may include `intent_label`, `intent_decision_source`, and `intent_confidence` when the flag is `1`.

## Rollback

Set the GitHub variable `INTENTWEAVE_DECISIONS_LABELER` to `0` (or remove it so deploy defaults to `0`) and redeploy. Responses return to the pre-labeling shape (no intent fields). No secret deletion is required.