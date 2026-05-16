"""
DynamoDB-backed session store for AWS Lambda deployments.

Design decisions:
- On-demand (PAY_PER_REQUEST) billing: zero cost when idle.
- Single get_item + single put_item per request (1 read + 1 write unit).
- Metadata is buffered in-process during a request and flushed in save(),
  avoiding extra DynamoDB calls while keeping the Session schema clean.
- TTL attribute enables automatic expiry at no extra cost.
- Numbers stored as Decimal (DynamoDB requirement); deserialized back to
  int/float on read.
"""
from __future__ import annotations

import decimal
import time
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr

from intentweave.models import Session
from intentweave.session_store import AbstractSessionStore


# ---------------------------------------------------------------------------
# Type coercion helpers (DynamoDB ↔ Python)
# ---------------------------------------------------------------------------

def _to_dynamo(value: Any) -> Any:
    """Recursively convert Python numerics to Decimal for DynamoDB storage."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return decimal.Decimal(str(value))
    if isinstance(value, int):
        return decimal.Decimal(value)
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value: Any) -> Any:
    """Recursively convert Decimal back to int/float after reading from DynamoDB."""
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Session ↔ DynamoDB item serialization
# ---------------------------------------------------------------------------

def _session_to_item(session: Session) -> dict[str, Any]:
    item: dict[str, Any] = {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "state": session.state,
        "iteration_count": decimal.Decimal(session.iteration_count),
        "required_slots": session.required_slots or [],
        "filled_slots": _to_dynamo(session.filled_slots),
        "missing_slots": session.missing_slots or [],
        "persona": session.persona,
    }
    # Omit None optional fields; DynamoDB cannot store None in a String attr
    if session.intent is not None:
        item["intent"] = session.intent
    if session.domain is not None:
        item["domain"] = session.domain
    return item


def _item_to_session(item: dict[str, Any]) -> Session:
    return Session(
        session_id=item["session_id"],
        user_id=item["user_id"],
        intent=item.get("intent") or None,
        domain=item.get("domain") or None,
        state=item["state"],
        iteration_count=int(item["iteration_count"]),
        required_slots=list(item.get("required_slots", [])),
        filled_slots=_from_dynamo(dict(item.get("filled_slots", {}))),
        missing_slots=list(item.get("missing_slots", [])),
        persona=item["persona"],
    )


# ---------------------------------------------------------------------------
# DynamoDB-backed store
# ---------------------------------------------------------------------------

class DynamoDBSessionStore(AbstractSessionStore):
    """
    Production session store backed by a single DynamoDB table.

    Cost model (on-demand):
      - 1 GetItem  per handle_user_message call  (~0.5 RCU  ≈ $0.0000007)
      - 1 PutItem  per handle_user_message call  (~1   WCU  ≈ $0.0000013)
      Total per query: < $0.000002 (under $2 per million requests)

    Metadata sidecar pattern:
      Metadata (e.g., consecutive_empty_updates counter) is buffered
      in-memory during a Lambda invocation and written to the same DynamoDB
      item in save(), so we never need an extra UpdateItem round-trip.
    """

    def __init__(
        self,
        table_name: str,
        ttl_days: int = 7,
        region_name: str | None = None,
    ) -> None:
        dynamodb = boto3.resource("dynamodb", region_name=region_name)
        self._table = dynamodb.Table(table_name)
        self._ttl_days = ttl_days
        # Per-invocation metadata buffer. Populated by get(), flushed by save().
        self._metadata_buffer: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def get(self, session_id: str) -> Session | None:
        response = self._table.get_item(Key={"session_id": session_id})
        item = response.get("Item")
        if item is None:
            return None
        # Warm the metadata buffer so set_metadata() doesn't require a
        # separate GetItem on the same invocation.
        self._metadata_buffer[session_id] = _from_dynamo(
            dict(item.get("metadata", {}))
        )
        return _item_to_session(item)

    def save(self, session: Session) -> None:
        item = _session_to_item(session)
        # Flush buffered metadata into the same item (zero extra WCUs).
        meta = self._metadata_buffer.get(session.session_id, {})
        if meta:
            item["metadata"] = _to_dynamo(meta)
        # TTL: epoch seconds at which DynamoDB will automatically delete this item.
        item["ttl"] = decimal.Decimal(int(time.time()) + self._ttl_days * 86400)
        self._table.put_item(Item=item)

    def delete(self, session_id: str) -> None:
        self._table.delete_item(Key={"session_id": session_id})
        self._metadata_buffer.pop(session_id, None)

    # ------------------------------------------------------------------
    # Metadata sidecar (buffered; flushed on save)
    # ------------------------------------------------------------------

    def get_metadata(self, session_id: str) -> dict[str, Any]:
        return dict(self._metadata_buffer.get(session_id, {}))

    def set_metadata(self, session_id: str, key: str, value: Any) -> None:
        if session_id not in self._metadata_buffer:
            self._metadata_buffer[session_id] = {}
        self._metadata_buffer[session_id][key] = value
