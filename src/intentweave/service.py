from typing import Any

from intentweave.clock import Clock
from intentweave.errors import (
    ThreadError,
    fingerprint_mismatch,
    invalid_request,
    thread_not_found,
)
from intentweave.fingerprint import diff_fingerprints, extract_fingerprint
from intentweave.models import ProviderResult, ThreadRecord
from intentweave.providers.base import MessageProvider
from intentweave.store.base import ThreadStore


class ThreadService:
    """Thread store + request router."""

    def __init__(
        self,
        store: ThreadStore,
        provider: MessageProvider,
        clock: Clock,
        *,
        soft_ttl_seconds: int = 300,
        hard_ttl_seconds: int = 3600,
    ) -> None:
        self._store = store
        self._provider = provider
        self._clock = clock
        self._soft_ttl = soft_ttl_seconds
        self._hard_ttl = hard_ttl_seconds

    def handle_messages(self, body: dict[str, Any]) -> dict[str, Any]:
        thread = body.get("thread")
        if not thread:
            return self._stateless(body)

        thread_type = thread.get("type")
        if thread_type == "create":
            return self._create_thread(body)
        if thread_type == "continue":
            return self._continue_thread(body, thread)
        raise invalid_request("thread.type must be 'create' or 'continue'.")

    def _stateless(self, body: dict[str, Any]) -> dict[str, Any]:
        model = _require_str(body, "model")
        messages = _require_messages(body)
        max_tokens = int(body.get("max_tokens") or 1024)
        result = self._provider.complete(
            model=model,
            messages=messages,
            system=body.get("system"),
            tools=body.get("tools"),
            max_tokens=max_tokens,
            request_meta={"thread": None},
        )
        return result.as_message_dict()

    def _create_thread(self, body: dict[str, Any]) -> dict[str, Any]:
        model = _require_str(body, "model")
        messages = _require_messages(body)
        max_tokens = int(body.get("max_tokens") or 1024)
        fingerprint = extract_fingerprint(body)

        result = self._provider.complete(
            model=model,
            messages=messages,
            system=body.get("system"),
            tools=body.get("tools"),
            max_tokens=max_tokens,
            request_meta={"thread": "create"},
        )
        now = self._clock.now()
        record = _record_from_result(
            result=result,
            thread_id=result.response_id,
            parent_response_id=None,
            fingerprint=fingerprint,
            system=body.get("system"),
            tools=body.get("tools"),
            messages=_append_assistant(messages, result),
            now=now,
            hard_ttl_seconds=self._hard_ttl,
        )
        self._store.put(record)
        return result.as_message_dict()

    def _continue_thread(self, body: dict[str, Any], thread: dict[str, Any]) -> dict[str, Any]:
        if "system" in body or "tools" in body:
            raise invalid_request("system and tools must not be sent on a thread continue request.")

        previous_id = thread.get("previous_message_id")
        if not previous_id:
            raise invalid_request("thread.previous_message_id is required for continue.")

        incoming_fp = extract_fingerprint(body)
        model = _require_str(body, "model")
        new_messages = body.get("messages")
        if new_messages is None:
            raise invalid_request("messages is required.")
        if not isinstance(new_messages, list):
            raise invalid_request("messages must be an array.")

        parent = self._store.try_begin_continue(previous_id)
        try:
            self._assert_continuable(parent)
            self._assert_fresh(parent)
            mismatched = diff_fingerprints(parent.fingerprint, incoming_fp)
            if mismatched:
                raise fingerprint_mismatch(mismatched)

            if parent.paused and new_messages:
                raise invalid_request(
                    "Cannot send new messages while the turn is paused; use an empty messages list."
                )
            if not parent.paused and not new_messages:
                raise invalid_request(
                    "messages must be non-empty unless resuming a pause_turn response."
                )

            full_messages = list(parent.messages)
            if new_messages:
                full_messages.extend(new_messages)

            max_tokens = int(body.get("max_tokens") or 1024)
            result = self._provider.complete(
                model=model,
                messages=full_messages,
                system=parent.system,
                tools=parent.tools,
                max_tokens=max_tokens,
                request_meta={
                    "thread": "continue",
                    "previous_message_id": previous_id,
                    "resume_pause": parent.paused and not new_messages,
                },
            )
            now = self._clock.now()

            child = _record_from_result(
                result=result,
                thread_id=parent.thread_id,
                parent_response_id=previous_id,
                fingerprint=parent.fingerprint,
                system=parent.system,
                tools=parent.tools,
                messages=_append_assistant(full_messages, result),
                now=now,
                hard_ttl_seconds=self._hard_ttl,
            )
            self._store.finish_continue(
                previous_id,
                new_record=child,
                mark_parent_continued=True,
            )
            return result.as_message_dict()
        except ThreadError:
            self._store.abort_continue(previous_id)
            raise
        except Exception:
            self._store.abort_continue(previous_id)
            raise

    def _assert_fresh(self, record: ThreadRecord) -> None:
        age = self._clock.now() - record.last_used_epoch
        if age > self._soft_ttl:
            raise thread_not_found("Thread expired (soft TTL).")

    def _assert_continuable(self, record: ThreadRecord) -> None:
        if record.refused:
            raise thread_not_found("Cannot continue after a refusal.")
        if record.stop_reason == "refusal":
            raise thread_not_found("Cannot continue after a refusal.")


def _record_from_result(
    *,
    result: ProviderResult,
    thread_id: str,
    parent_response_id: str | None,
    fingerprint: dict[str, Any],
    system: Any | None,
    tools: Any | None,
    messages: list[dict[str, Any]],
    now: float,
    hard_ttl_seconds: int,
) -> ThreadRecord:
    refused = result.stop_reason == "refusal"
    paused = result.stop_reason == "pause_turn"
    ttl_epoch = int(now) + hard_ttl_seconds
    return ThreadRecord(
        response_id=result.response_id,
        thread_id=thread_id,
        parent_response_id=parent_response_id,
        fingerprint=fingerprint,
        system=system,
        tools=tools,
        messages=messages,
        model=result.model,
        stop_reason=result.stop_reason,
        assistant_message=result.as_message_dict(),
        continued=False,
        continue_in_flight=False,
        last_used_epoch=now,
        ttl_epoch=ttl_epoch,
        refused=refused,
        paused=paused,
    )


def _append_assistant(
    messages: list[dict[str, Any]], result: ProviderResult
) -> list[dict[str, Any]]:
    out = list(messages)
    out.append({"role": "assistant", "content": result.content})
    return out


def _require_str(body: dict[str, Any], key: str) -> str:
    val = body.get(key)
    if not isinstance(val, str) or not val:
        raise invalid_request(f"{key} is required.")
    return val


def _require_messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) == 0:
        raise invalid_request("messages must be a non-empty array for create.")
    return messages
