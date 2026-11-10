# Contributing to IntentWeave

Thanks for helping improve IntentWeave. This project is pre-1.0; interfaces may change until the first stable release.

## Development setup

**Requirements:** Python 3.12+, pip, optional [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) for template validation.

```bash
git clone https://github.com/rajatarun/IntentWeave.git
cd IntentWeave
make install
export PATH="$HOME/.local/bin:$PATH"   # if pip installs user scripts off PATH
make test
make lint
```

Local examples (no AWS):

```bash
PYTHONPATH=src python3 examples/local_thread_lifecycle.py
```

### Environment

| Variable | Purpose |
| --- | --- |
| `THREADS_TABLE_NAME` | Unset for in-memory store (default for tests) |
| `INTENTWEAVE_PROVIDER` | `mock` (default) |

## Tests

```bash
make test          # pytest
make lint          # ruff check + format check
```

DynamoDB behavior is covered with **moto**; no live AWS account needed for CI-parity tests.

Optional SAM checks (requires SAM CLI on PATH):

```bash
make validate
make sam-build
```

## Code style

- **Ruff** for lint and format (`pyproject.toml`, line length 100).
- Type hints on public functions; match existing patterns in `src/intentweave/`.
- Keep handlers thin; put logic in `ThreadService`, stores, and providers.

Run `ruff format src tests` before committing if format check fails.

## Pull requests

1. Fork and branch from `main` (use a descriptive branch name).
2. Keep changes focused; update docs when behavior or env vars change.
3. Ensure `make test` and `make lint` pass.
4. Describe **what** and **why** in the PR; link related discussions if any.

We do not require a Contributor License Agreement for Apache-2.0 contributions; you retain copyright and license your contribution under the same license as the project.

## Reporting bugs and ideas

Use GitHub issues for bugs and feature requests once templates are available. For security issues, see [SECURITY.md](SECURITY.md) — do not file public issues for vulnerabilities.
