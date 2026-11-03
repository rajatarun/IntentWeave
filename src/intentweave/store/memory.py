from intentweave.errors import already_continued, continue_in_flight, thread_not_found
from intentweave.models import ThreadRecord


class MemoryThreadStore:
    """In-process thread store for tests and local development."""

    def __init__(self) -> None:
        self._items: dict[str, ThreadRecord] = {}

    def get(self, response_id: str) -> ThreadRecord | None:
        rec = self._items.get(response_id)
        if rec is None:
            return None
        return ThreadRecord.from_item(rec.to_item())

    def put(self, record: ThreadRecord) -> None:
        self._items[record.response_id] = ThreadRecord.from_item(record.to_item())

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
