# Examples

Runnable scripts that exercise IntentWeave without deploying to AWS.

| Script | What it shows |
| --- | --- |
| [local_thread_lifecycle.py](local_thread_lifecycle.py) | Create a thread, then continue with only new messages |
| [pause_turn_resume.py](pause_turn_resume.py) | `pause_turn` stop reason and empty-messages resume |
| [invoke_lambda_handler.py](invoke_lambda_handler.py) | HTTP API-shaped events through `lambda_handler` |

## Prerequisites

```bash
make install
export PATH="$HOME/.local/bin:$PATH"
```

## Run

```bash
PYTHONPATH=src python3 examples/local_thread_lifecycle.py
PYTHONPATH=src python3 examples/pause_turn_resume.py
PYTHONPATH=src python3 examples/invoke_lambda_handler.py
```
