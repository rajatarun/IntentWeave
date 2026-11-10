#!/usr/bin/env python3
"""POST /v1/messages through the Lambda HTTP handler (in-memory store)."""

import json
import os

# Force in-memory store and mock provider before handler module initializes ThreadService.
os.environ.pop("THREADS_TABLE_NAME", None)
os.environ.setdefault("INTENTWEAVE_PROVIDER", "mock")

from handler import lambda_handler  # noqa: E402


def api_event(method: str, path: str, body: dict) -> dict:
    return {
        "rawPath": path,
        "body": json.dumps(body),
        "requestContext": {"http": {"method": method}, "stage": "$default"},
    }


def main() -> None:
    create = lambda_handler(
        api_event(
            "POST",
            "/v1/messages",
            {
                "model": "claude-test-1",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "Hi"}],
                "thread": {"type": "create"},
            },
        ),
        None,
    )
    body = json.loads(create["body"])
    print("HTTP", create["statusCode"], body["id"], body["content"][0]["text"])


if __name__ == "__main__":
    main()
