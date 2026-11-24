"""Cryptographic thread compaction checkpoints for IntentWeave."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from intentweave.errors import (
    history_integrity_violation,
    invalid_request,
    thread_not_found,
)
from intentweave.fingerprint import history_digest, verify_history_digest
from intentweave.models import ThreadRecord


@dataclass(frozen=True)
class ThreadCheckpoint:
    """Immutable cryptographic compaction checkpoint covering turns ``0..up_to_turn``."""

    checkpoint_id: str
    thread_id: str
    up_to_turn: int
    covered_digest: str
    summary_text: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "thread_id": self.thread_id,
            "up_to_turn": self.up_to_turn,
            "covered_digest": self.covered_digest,
            "summary_text": self.summary_text,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThreadCheckpoint:
        return cls(
            checkpoint_id=str(data["checkpoint_id"]),
            thread_id=str(data["thread_id"]),
            up_to_turn=int(data["up_to_turn"]),
            covered_digest=str(data["covered_digest"]),
            summary_text=str(data["summary_text"]),
            created_at=str(data["created_at"]),
        )


def build_checkpoint(
    ordered_records: list[ThreadRecord],
    *,
    summary_text: str,
    up_to_turn: int | None = None,
    checkpoint_id: str | None = None,
    created_at: str | None = None,
) -> ThreadCheckpoint:
    """Build a cryptographically bound compaction checkpoint for turns ``0..up_to_turn``."""
    if not ordered_records:
        raise thread_not_found("Thread not found.")

    if not isinstance(summary_text, str) or not summary_text.strip():
        raise invalid_request("summary_text must be a non-empty string.")

    target_turn = len(ordered_records) - 1 if up_to_turn is None else up_to_turn
    if target_turn < 0 or target_turn >= len(ordered_records):
        raise invalid_request(
            f"up_to_turn must be between 0 and {len(ordered_records) - 1}, got {target_turn}."
        )

    selected = ordered_records[: target_turn + 1]
    for rec in selected:
        if not verify_history_digest(rec.fingerprint, system=rec.system, messages=rec.messages):
            raise history_integrity_violation()

    target_rec = selected[-1]
    covered_digest = target_rec.fingerprint.get("history_digest") or history_digest(
        system=target_rec.system,
        messages=target_rec.messages,
    )

    return ThreadCheckpoint(
        checkpoint_id=checkpoint_id or f"ckpt_{uuid.uuid4().hex[:16]}",
        thread_id=ordered_records[0].thread_id,
        up_to_turn=target_turn,
        covered_digest=covered_digest,
        summary_text=summary_text,
        created_at=created_at or datetime.now(UTC).isoformat(),
    )


def verify_checkpoint(
    checkpoint: ThreadCheckpoint | dict[str, Any],
    ordered_records: list[ThreadRecord],
) -> bool:
    """Verify that a checkpoint's ``covered_digest`` matches the thread at ``up_to_turn``."""
    ckpt = (
        checkpoint
        if isinstance(checkpoint, ThreadCheckpoint)
        else ThreadCheckpoint.from_dict(checkpoint)
    )
    if not ordered_records:
        return False
    if ordered_records[0].thread_id != ckpt.thread_id:
        return False
    if ckpt.up_to_turn < 0 or ckpt.up_to_turn >= len(ordered_records):
        return False

    target = ordered_records[ckpt.up_to_turn]
    if not verify_history_digest(
        target.fingerprint, system=target.system, messages=target.messages
    ):
        return False

    actual_digest = history_digest(system=target.system, messages=target.messages)
    return actual_digest == ckpt.covered_digest


def select_post_checkpoint_messages(
    ordered_records: list[ThreadRecord],
    checkpoint: ThreadCheckpoint | dict[str, Any],
) -> list[tuple[int, dict[str, Any]]]:
    """Return ``(message_index, message)`` pairs strictly after ``checkpoint.up_to_turn``."""
    ckpt = (
        checkpoint
        if isinstance(checkpoint, ThreadCheckpoint)
        else ThreadCheckpoint.from_dict(checkpoint)
    )
    if not verify_checkpoint(ckpt, ordered_records):
        raise history_integrity_violation()

    covered_message_count = len(ordered_records[ckpt.up_to_turn].messages)
    leaf_messages = list(ordered_records[-1].messages)
    return [
        (idx, msg)
        for idx, msg in enumerate(leaf_messages)
        if idx >= covered_message_count
    ]
