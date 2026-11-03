from typing import Protocol

from intentweave.models import ThreadRecord


class ThreadStore(Protocol):
    def get(self, response_id: str) -> ThreadRecord | None: ...

    def put(self, record: ThreadRecord) -> None: ...

    def try_begin_continue(self, response_id: str) -> ThreadRecord:
        """Mark continue in-flight. Raises ThreadError on conflict."""

    def finish_continue(
        self,
        parent_id: str,
        *,
        new_record: ThreadRecord,
        mark_parent_continued: bool,
    ) -> None:
        """Persist child turn and update parent continuation state."""

    def abort_continue(self, response_id: str) -> None:
        """Clear in-flight flag after a failed provider call."""
