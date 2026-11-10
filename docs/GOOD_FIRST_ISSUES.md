# Good first issues (draft for maintainers)

Concrete, scoped tasks discovered in the codebase. Maintainers can copy these into GitHub issues.

---

## 1. Implement Anthropic `MessageProvider`

**Files:** `src/intentweave/providers/anthropic.py` (new), `src/intentweave/providers/registry.py`

**Acceptance criteria:**

- `INTENTWEAVE_PROVIDER=anthropic` returns a working provider when `ANTHROPIC_API_KEY` is set.
- Create and continue paths call the Messages API with merged history from `ThreadRecord`.
- Unit tests use `responses` or VCR fixtures; no live API in CI.
- Errors from Anthropic map to existing `ThreadError` types where possible.

---

## 2. Implement Bedrock Converse `MessageProvider`

**Files:** `src/intentweave/providers/bedrock.py` (new), `template.yaml` IAM

**Acceptance criteria:**

- `INTENTWEAVE_PROVIDER=bedrock` invokes Converse with correct model id.
- SAM template grants least-privilege `bedrock:InvokeModel` on configured models.
- Moto or local integration test with skipped-live marker for optional manual run.

---

## 3. Publish OpenAPI description for `/v1/messages`

**Files:** `docs/openapi.yaml` (new), README link

**Acceptance criteria:**

- Documents `POST /v1/messages` request/response and documented error envelope.
- Thread create/continue variants with required fingerprint fields.
- Validated with an OpenAPI linter in CI (optional job).

---

## 4. Add OpenTelemetry spans to `lambda_handler`

**Files:** `src/intentweave/api.py`, `docs/INTEGRATIONS.md`

**Acceptance criteria:**

- Optional tracing when OTEL exporter env vars are set; no overhead when unset.
- Span attributes: `thread.type`, HTTP status, `error_code` on failures.
- Documented setup for Lambda ADOT.

---

## 5. API Gateway authorizer example in SAM

**Files:** `template.yaml`, `docs/design/SECURITY_NOTES.md`

**Acceptance criteria:**

- Optional parameter to attach JWT or Lambda authorizer (disabled by default).
- README section explains production auth is operator responsibility.

---

## 6. Redis `ThreadStore` sketch

**Files:** `src/intentweave/store/redis.py` (new), tests with fakeredis or mock

**Acceptance criteria:**

- Implements `ThreadStore` with same concurrency semantics as DynamoDB.
- Document when to choose Redis vs DynamoDB.

---

## 7. Contract test: stage-prefixed paths

**Files:** `tests/test_api_handler.py`

**Acceptance criteria:**

- Already covered for `/prod/health` and `/prod/v1/messages`; extend with `$default` regression table-driven test if missing edge cases.

---

## 8. Improve handler import path for examples

**Files:** `examples/invoke_lambda_handler.py`, `src/handler.py`

**Acceptance criteria:**

- Example documents `PYTHONPATH=src` and does not require package install.
- Optional: expose `create_service()` factory for testing without module-level globals.

---

## 9. Fingerprint: document `betas` → `feature_flags` mapping

**Files:** `src/intentweave/fingerprint.py`, README

**Acceptance criteria:**

- Docstring or `docs/design/FINGERPRINT.md` lists all fingerprint fields and Claude parity notes.
- Test case for `betas` array normalization if not already present.

---

## 10. Makefile: put user-local bin on PATH for `test` target

**Files:** `Makefile`

**Acceptance criteria:**

- `make test` works when pytest is installed via `pip install --user`.
- No breaking change for CI (pytest already on PATH).
