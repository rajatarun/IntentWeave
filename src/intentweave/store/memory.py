from typing import Any

from intentweave.errors import already_continued, continue_in_flight, thread_not_found
from intentweave.models import ThreadRecord


class MemoryThreadStore:
    """In-process thread store for tests and local development."""

    def __init__(self) -> None:
        self._items: dict[str, ThreadRecord] = {}
        self._checkpoints: list[dict[str, Any]] = []

    def get(self, response_id: str) -> ThreadRecord | None:
        rec = self._items.get(response_id)
        if rec is None:
            return None
        return ThreadRecord.from_item(rec.to_item())

    def list_by_thread(self, thread_id: str) -> list[ThreadRecord]:
        return [
            ThreadRecord.from_item(rec.to_item())
            for rec in self._items.values()
            if rec.thread_id == thread_id
        ]

    def put(self, record: ThreadRecord) -> None:
        self._items[record.response_id] = ThreadRecord.from_item(record.to_item())

    def put_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        self._checkpoints = [
            c for c in self._checkpoints if c["checkpoint_id"] != checkpoint["checkpoint_id"]
        ]
        self._checkpoints.append(dict(checkpoint))

    def list_checkpoints(self, thread_id: str) -> list[dict[str, Any]]:
        resolved = thread_id
        if not self.list_by_thread(thread_id):
            single = self.get(thread_id)
            if single is not None:
                resolved = single.thread_id
        matched = [dict(c) for c in self._checkpoints if c["thread_id"] == resolved]
        matched.sort(key=lambda c: int(c["up_to_turn"]))
        return matched

    def get_latest_checkpoint(self, thread_id: str) -> dict[str, Any] | None:
        matched = self.list_checkpoints(thread_id)
        if not matched:
            return None
        return matched[-1]

    def try_begin_continue(self, response_id: str) -> ThreadRecord:
        rec = self.get(response_id)
        if rec is None:
            raise thread_not_found()
        if rec.continued:
            raise already_continued()
        if rec.continue_in_flight:
            raise continue_in_flight()
        rec.continue_in_flight = True
        self.put(rec)
        return rec

    def finish_continue(
        self,
        parent_id: str,
        *,
        new_record: ThreadRecord,
        mark_parent_continued: bool,
    ) -> None:
        parent = self.get(parent_id)
        if parent is None:
            raise thread_not_found()
        parent.continue_in_flight = False
        if mark_parent_continued:
            parent.continued = True
        self.put(parent)
        self.put(new_record)

    def abort_continue(self, response_id: str) -> None:
        rec = self.get(response_id)
        if rec is None:
            return
        rec.continue_in_flight = False
        self.put(rec)
