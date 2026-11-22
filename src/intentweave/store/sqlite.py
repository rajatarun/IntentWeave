"""Durable WAL SQLite ThreadStore with atomic CAS continuation locks."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from intentweave.errors import already_continued, continue_in_flight, thread_not_found
from intentweave.models import ThreadRecord


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

    def put(self, record: ThreadRecord) -> None:
        with self._lock:
            self._write_unlocked(record)
            self._conn.commit()

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
