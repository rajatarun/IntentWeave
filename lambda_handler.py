"""
IntentWeave Lambda entry point.

Handles HTTP API (v2) events from API Gateway.
Clients are initialised once outside the handler to benefit from
Lambda warm-start container reuse (no per-request boto3 init cost).

To connect real ContextWeave and ToolWeave implementations:
  1. Implement intentweave.clients.ContextWeaveClient
  2. Implement intentweave.clients.ToolWeaveClient
  3. Replace the stub instances below with your concrete classes,
     reading endpoint/auth config from os.environ.
"""
from __future__ import annotations

import json
import logging
import os

from intentweave.clients import ContextWeaveClient, ToolWeaveClient
from intentweave.dynamodb_store import DynamoDBSessionStore
from intentweave.models import Session
from intentweave.orchestrator import configure, handle_user_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Stub clients — replace with production implementations
# ---------------------------------------------------------------------------

class _StubContextWeaveClient(ContextWeaveClient):
    """
    Placeholder. Replace with a real HTTP client that calls your
    ContextWeave service.  The analyze() and final_validation() signatures
    and return shapes are contractually fixed by the spec.
    """

    def analyze(self, session: Session, user_message: str) -> dict:
        # Real implementation: POST to CONTEXT_WEAVE_ENDPOINT with session + message
        raise NotImplementedError(
            "Set CONTEXT_WEAVE_ENDPOINT and implement _StubContextWeaveClient.analyze()"
        )

    def final_validation(self, session: Session) -> dict:
        raise NotImplementedError(
            "Set CONTEXT_WEAVE_ENDPOINT and implement _StubContextWeaveClient.final_validation()"
        )


class _StubToolWeaveClient(ToolWeaveClient):
    """
    Placeholder. Replace with a real MCP client that calls your
    ToolWeave service.
    """

    def execute(self, tool_name: str, payload: dict) -> dict:
        raise NotImplementedError(
            "Set TOOL_WEAVE_ENDPOINT and implement _StubToolWeaveClient.execute()"
        )


# ---------------------------------------------------------------------------
# One-time initialisation (warm-start reuse)
# ---------------------------------------------------------------------------

_TABLE_NAME = os.environ.get("SESSIONS_TABLE_NAME", "")
_TTL_DAYS = int(os.environ.get("SESSION_TTL_DAYS", "7"))
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

if not _TABLE_NAME:
    raise RuntimeError("SESSIONS_TABLE_NAME environment variable is required")

_session_store = DynamoDBSessionStore(
    table_name=_TABLE_NAME,
    ttl_days=_TTL_DAYS,
    region_name=_AWS_REGION,
)

configure(
    context_weave=_StubContextWeaveClient(),
    tool_weave=_StubToolWeaveClient(),
)


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def handler(event: dict, context: object) -> dict:
    """
    Processes one user message turn.

    Expected request body (JSON):
    {
        "session_id": str,       # required
        "user_message": str,     # required
        "user_id":     str,      # optional, default "anonymous"
        "persona":     str       # optional, default "PROFESSIONAL"
    }

    Response body matches the strict IntentWeave output contract:
    {
        "user_message":        str,
        "system_transparency": str,
        "state":               str,
        "internal":            { intent, domain, slots, missing_slots,
                                 confidence, iteration_count, persona }
    }
    """
    try:
        raw_body = event.get("body") or "{}"
        body: dict = json.loads(raw_body)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Malformed request body: %s", exc)
        return _error_response(400, "Request body must be valid JSON.")

    session_id: str | None = body.get("session_id")
    user_message: str | None = body.get("user_message")

    if not session_id or not user_message:
        return _error_response(400, "session_id and user_message are required.")

    user_id: str = body.get("user_id", "anonymous")
    persona: str = body.get("persona", "PROFESSIONAL")

    logger.info("session=%s persona=%s message_len=%d", session_id, persona, len(user_message))

    try:
        result = handle_user_message(
            session_id=session_id,
            user_message=user_message,
            user_id=user_id,
            persona=persona,
            _store=_session_store,
        )
    except Exception as exc:
        logger.exception("Orchestrator raised unexpectedly: %s", exc)
        return _error_response(500, "Internal orchestration error.")

    logger.info("session=%s state=%s", session_id, result.get("state"))

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result),
    }


def _error_response(status: int, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }
