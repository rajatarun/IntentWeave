"""Durable WAL SQLite ThreadStore with atomic CAS continuation locks and thread forking."""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from intentweave.compaction import build_checkpoint
from intentweave.errors import (
    already_continued,
    continue_in_flight,
    history_integrity_violation,
    invalid_request,
    thread_not_found,
)
from intentweave.fingerprint import attach_history_digest, history_digest, verify_history_digest
from intentweave.models import ThreadRecord


def order_thread_records(records: list[ThreadRecord]) -> list[ThreadRecord]:
    """Order a thread's records from root turn (index 0) to leaf turn."""
    if not records:
        return []
    roots = [rec for rec in records if rec.parent_response_id is None]
    if len(roots) != 1:
        raise history_integrity_violation()
    child_by_parent: dict[str, ThreadRecord] = {}
    for rec in records:
        if rec.parent_response_id is not None:
            child_by_parent[rec.parent_response_id] = rec

    ordered: list[ThreadRecord] = []
    seen: set[str] = set()
    curr: ThreadRecord | None = roots[0]
    while curr is not None:
        if curr.response_id in seen:
            raise history_integrity_violation()
        seen.add(curr.response_id)
        ordered.append(curr)
        curr = child_by_parent.get(curr.response_id)

    if len(ordered) != len(records):
        raise history_integrity_violation()
    return ordered


def build_forked_records(
    ordered_source: list[ThreadRecord],
    *,
    new_thread_id: str | None = None,
    up_to_turn: int | None = None,
) -> tuple[list[ThreadRecord], dict[str, Any]]:
    """Construct cryptographically valid forked ThreadRecords for turns 0..up_to_turn."""
    if not ordered_source:
        raise thread_not_found("Source thread not found.")

    fork_turn = len(ordered_source) - 1 if up_to_turn is None else up_to_turn
    if fork_turn < 0 or fork_turn >= len(ordered_source):
        raise invalid_request(
            f"up_to_turn must be between 0 and {len(ordered_source) - 1}, got {fork_turn}."
        )

    selected = ordered_source[: fork_turn + 1]
    for rec in selected:
        if not verify_history_digest(rec.fingerprint, system=rec.system, messages=rec.messages):
            raise history_integrity_violation()

    source_thread_id = ordered_source[0].thread_id
    parent_record = selected[-1]
    parent_digest = parent_record.fingerprint.get("history_digest") or history_digest(
        system=parent_record.system,
        messages=parent_record.messages,
    )

    fork_thread_id = new_thread_id or f"fork_{uuid.uuid4().hex[:16]}"
    forked_records: list[ThreadRecord] = []
    prev_response_id: str | None = None

    for idx, src in enumerate(selected):
        resp_id = fork_thread_id if idx == 0 else f"{fork_thread_id}_t{idx}"
        messages_copy = copy.deepcopy(src.messages)
        system_copy = copy.deepcopy(src.system)
        tools_copy = copy.deepcopy(src.tools)
        fp_copy = attach_history_digest(
            copy.deepcopy(src.fingerprint),
            system=system_copy,
            messages=messages_copy,
        )
        assistant_copy = copy.deepcopy(src.assistant_message)
        if isinstance(assistant_copy, dict):
            assistant_copy["id"] = resp_id

        forked = ThreadRecord(
            response_id=resp_id,
            thread_id=fork_thread_id,
            parent_response_id=prev_response_id,
            fingerprint=fp_copy,
            system=system_copy,
            tools=tools_copy,
            messages=messages_copy,
            model=src.model,
            provider=src.provider,
            model_policy=src.model_policy,
            pinned_model=src.pinned_model,
            stop_reason=src.stop_reason,
            assistant_message=assistant_copy,
            continued=idx < fork_turn,
            continue_in_flight=False,
            last_used_epoch=src.last_used_epoch,
            ttl_epoch=src.ttl_epoch,
            refused=src.refused,
            paused=src.paused,
            parent_thread_id=source_thread_id,
            parent_turn=fork_turn,
            parent_digest=parent_digest,
        )
        forked_records.append(forked)
        prev_response_id = resp_id

    summary = {
        "thread_id": fork_thread_id,
        "head_response_id": forked_records[-1].response_id,
        "turns_copied": len(forked_records),
        "parent_thread_id": source_thread_id,
        "parent_turn": fork_turn,
        "parent_digest": parent_digest,
        "head_digest": forked_records[-1].fingerprint["history_digest"],
    }
    return forked_records, summary


class SQLiteThreadStore:
    """Thread-safe WAL SQLite store implementing the ``ThreadStore`` protocol."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        path_str = str(db_path)
        if path_str != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path_str, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intent_threads (
                    response_id TEXT PRIMARY KEY,
                    item_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    up_to_turn INTEGER NOT NULL,
                    covered_digest TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_thread_checkpoints_thread_turn
                ON thread_checkpoints (thread_id, up_to_turn DESC, created_at DESC)
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _read_unlocked(self, response_id: str) -> ThreadRecord | None:
        row = self._conn.execute(
            "SELECT item_json FROM intent_threads WHERE response_id = ?",
            (response_id,),
        ).fetchone()
        if row is None:
            return None
        return ThreadRecord.from_item(json.loads(row["item_json"]))

    def _list_by_thread_unlocked(self, thread_id: str) -> list[ThreadRecord]:
        rows = self._conn.execute("SELECT item_json FROM intent_threads").fetchall()
        records: list[ThreadRecord] = []
        for row in rows:
            item = json.loads(row["item_json"])
            if item.get("thread_id") == thread_id:
                records.append(ThreadRecord.from_item(item))
        return records

    def _write_unlocked(self, record: ThreadRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO intent_threads (response_id, item_json)
            VALUES (?, ?)
            ON CONFLICT(response_id) DO UPDATE SET item_json = excluded.item_json
            """,
            (record.response_id, json.dumps(record.to_item())),
        )

    def get(self, response_id: str) -> ThreadRecord | None:
        with self._lock:
            return self._read_unlocked(response_id)

    def list_by_thread(self, thread_id: str) -> list[ThreadRecord]:
        """Return all stored turn records belonging to ``thread_id``."""
        with self._lock:
            return self._list_by_thread_unlocked(thread_id)

    def put(self, record: ThreadRecord) -> None:
        with self._lock:
            self._write_unlocked(record)
            self._conn.commit()

    def fork_thread(
        self,
        source_thread_id: str,
        *,
        new_thread_id: str | None = None,
        up_to_turn: int | None = None,
    ) -> dict[str, Any]:
        """Atomically fork turns ``0..up_to_turn`` into a new cryptographically verified thread."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                records = self._list_by_thread_unlocked(source_thread_id)
                if not records:
                    single = self._read_unlocked(source_thread_id)
                    if single is not None:
                        records = self._list_by_thread_unlocked(single.thread_id)
                if not records:
                    self._conn.rollback()
                    raise thread_not_found(f"Thread '{source_thread_id}' not found.")

                ordered = order_thread_records(records)
                forked_records, summary = build_forked_records(
                    ordered,
                    new_thread_id=new_thread_id,
                    up_to_turn=up_to_turn,
                )

                target_tid = summary["thread_id"]
                if self._list_by_thread_unlocked(target_tid) or self._read_unlocked(target_tid):
                    self._conn.rollback()
                    raise invalid_request(f"Target thread_id '{target_tid}' already exists.")

                for rec in forked_records:
                    self._write_unlocked(rec)
                self._conn.commit()
                return summary
            except Exception:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise

    def _resolve_thread_id_unlocked(self, thread_id: str) -> str:
        if self._list_by_thread_unlocked(thread_id):
            return thread_id
        single = self._read_unlocked(thread_id)
        if single is not None:
            return single.thread_id
        return thread_id

    @staticmethod
    def _row_to_checkpoint(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "checkpoint_id": row["checkpoint_id"],
            "thread_id": row["thread_id"],
            "up_to_turn": int(row["up_to_turn"]),
            "covered_digest": row["covered_digest"],
            "summary_text": row["summary_text"],
            "created_at": row["created_at"],
        }

    def put_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        """Persist a compaction checkpoint record in ``thread_checkpoints``."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO thread_checkpoints (
                    checkpoint_id,
                    thread_id,
                    up_to_turn,
                    covered_digest,
                    summary_text,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    thread_id = excluded.thread_id,
                    up_to_turn = excluded.up_to_turn,
                    covered_digest = excluded.covered_digest,
                    summary_text = excluded.summary_text,
                    created_at = excluded.created_at
                """,
                (
                    checkpoint["checkpoint_id"],
                    checkpoint["thread_id"],
                    int(checkpoint["up_to_turn"]),
                    checkpoint["covered_digest"],
                    checkpoint["summary_text"],
                    checkpoint["created_at"],
                ),
            )
            self._conn.commit()

    def create_checkpoint(
        self,
        thread_id: str,
        *,
        summary_text: str,
        up_to_turn: int | None = None,
    ) -> dict[str, Any]:
        """Atomically create and persist a cryptographic compaction checkpoint."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                records = self._list_by_thread_unlocked(thread_id)
                if not records:
                    single = self._read_unlocked(thread_id)
                    if single is not None:
                        records = self._list_by_thread_unlocked(single.thread_id)
                if not records:
                    self._conn.rollback()
                    raise thread_not_found(f"Thread '{thread_id}' not found.")

                ordered = order_thread_records(records)
                checkpoint = build_checkpoint(
                    ordered,
                    summary_text=summary_text,
                    up_to_turn=up_to_turn,
                )
                payload = checkpoint.to_dict()
                self._conn.execute(
                    """
                    INSERT INTO thread_checkpoints (
                        checkpoint_id,
                        thread_id,
                        up_to_turn,
                        covered_digest,
                        summary_text,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["checkpoint_id"],
                        payload["thread_id"],
                        payload["up_to_turn"],
                        payload["covered_digest"],
                        payload["summary_text"],
                        payload["created_at"],
                    ),
                )
                self._conn.commit()
                return payload
            except Exception:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise

    def list_checkpoints(self, thread_id: str) -> list[dict[str, Any]]:
        """Return all compaction checkpoints for ``thread_id`` ordered by turn."""
        with self._lock:
            resolved_tid = self._resolve_thread_id_unlocked(thread_id)
            rows = self._conn.execute(
                """
                SELECT checkpoint_id, thread_id, up_to_turn, covered_digest,
                       summary_text, created_at
                FROM thread_checkpoints
                WHERE thread_id = ?
                ORDER BY up_to_turn ASC, rowid ASC
                """,
                (resolved_tid,),
            ).fetchall()
            return [self._row_to_checkpoint(row) for row in rows]

    def get_latest_checkpoint(self, thread_id: str) -> dict[str, Any] | None:
        """Return the checkpoint covering the highest turn index for ``thread_id``."""
        with self._lock:
            resolved_tid = self._resolve_thread_id_unlocked(thread_id)
            row = self._conn.execute(
                """
                SELECT checkpoint_id, thread_id, up_to_turn, covered_digest,
                       summary_text, created_at
                FROM thread_checkpoints
                WHERE thread_id = ?
                ORDER BY up_to_turn DESC, rowid DESC
                LIMIT 1
                """,
                (resolved_tid,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_checkpoint(row)

    def try_begin_continue(self, response_id: str) -> ThreadRecord:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rec = self._read_unlocked(response_id)
                if rec is None:
                    self._conn.rollback()
                    raise thread_not_found()
                if rec.continued:
                    self._conn.rollback()
                    raise already_continued()
                if rec.continue_in_flight:
                    self._conn.rollback()
                    raise continue_in_flight()
                rec.continue_in_flight = True
                self._write_unlocked(rec)
                self._conn.commit()
                return rec
            except Exception:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise

    def finish_continue(
        self,
        parent_id: str,
        *,
        new_record: ThreadRecord,
        mark_parent_continued: bool,
    ) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                parent = self._read_unlocked(parent_id)
                if parent is None:
                    self._conn.rollback()
                    raise thread_not_found()
                parent.continue_in_flight = False
                if mark_parent_continued:
                    parent.continued = True
                self._write_unlocked(parent)
                self._write_unlocked(new_record)
                self._conn.commit()
            except Exception:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise

    def abort_continue(self, response_id: str) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rec = self._read_unlocked(response_id)
                if rec is not None:
                    rec.continue_in_flight = False
                    self._write_unlocked(rec)
                self._conn.commit()
            except Exception:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise
