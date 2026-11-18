# Gemini Decisions API — intent labeling

IntentWeave can label the latest user turn on **thread create/continue** using the Gemini Decisions API (`gemini-decision-1`, Developer API `v1beta`) when `INTENTWEAVE_DECISIONS_LABELER=1`. The feature is **off by default**; with the flag unset, responses match the pre-labeling API shape.

## Questions

Each classify call sends one shared `input` string (latest user text) and two questions:

| Key | Type | Purpose |
| --- | --- | --- |
| `intent` | `choice` | Pick one of `task`, `question`, `creative`, `tool_use`, `continuation`, `other` |
| `is_small_talk` | `noul` | Whether the turn is primarily small talk |

If `is_small_talk` has high `noul` and `confidence`, the label is `small_talk` regardless of the choice question. Otherwise the choice answer is used when `confidence` meets `INTENTWEAVE_DECISIONS_MIN_CONFIDENCE` (default `0.5`).

## Fallback

The heuristic labeler runs when:

- the flag is on but `GEMINI_API_KEY` is missing
- the API errors, times out (~`INTENTWEAVE_DECISIONS_TIMEOUT_S`, default `1.5`)
- the response is malformed
- confidence is below the minimum

`intent_decision_source` is `heuristic`, `gemini_decisions`, or `gemini_decisions_fallback`.

## Response fields (optional)

When labeling is enabled, successful thread responses may include:

- `intent_label`
- `intent_decision_source`
- `intent_confidence`

Fingerprint fields and required Claude-shaped fields are unchanged.

## Auth and deploy

- API key: `GEMINI_API_KEY` (environment / Secrets Manager — never committed).
- Lambda dependency: `google-genai>=3.2` in `src/requirements.txt`; client is constructed only when the flag and key are set.

## Telemetry

Classification spans are written with `operation=classify_question` when `OBSERVATORY_METRICS_TABLE` is set, using the vendored `contracts/observatory_metrics_item.json` (v2.0.0).

## References

- [Decisions API documentation](https://aistudio.google.com/docs/decisions-api)