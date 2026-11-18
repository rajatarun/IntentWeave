"""Best-effort observatory metrics for intent classification spans."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_OPERATION = "classify_question"
_SERVICE = "intentweave"
_TTL_SECONDS = 90 * 24 * 60 * 60
_table = None


def _table_resource():
    global _table
    name = os.environ.get("OBSERVATORY_METRICS_TABLE")
    if not name:
        return None
    if _table is None:
        import boto3

        _table = boto3.resource("dynamodb").Table(name)
    return _table


def emit_intent_label_metric(
    *,
    trace_id: str | None,
    label: str,
    source: str,
    confidence: float,
    model: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S.%f")
    span_id = trace_id or uuid.uuid4().hex
    item: dict[str, Any] = {
        "pk": f"OBSERVATORY#{_OPERATION}",
        "sk": f"{now_iso}#{span_id}",
        "trace_id": span_id,
        "operation": _OPERATION,
        "timestamp": now_iso,
        "span_date": now_iso[:10],
        "ttl": int(time.time()) + _TTL_SECONDS,
        "service": _SERVICE,
        "decision": label,
        "decision_reason": source,
        "intent_confidence": round(float(confidence), 6),
    }
    if model:
        item["model"] = model
    if extra:
        item.update(extra)

    table = _table_resource()
    if table is not None:
        try:
            table.put_item(Item=item)
        except Exception:
            logger.warning("observatory_metric_write_failed", exc_info=True)
    return item
