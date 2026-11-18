from typing import Any

from intentweave.clock import Clock
from intentweave.errors import (
    ThreadError,
    fingerprint_mismatch,
    history_integrity_violation,
    invalid_request,
    model_policy_violation,
    thread_not_found,
)
from intentweave.fingerprint import (
    attach_history_digest,
    diff_fingerprints,
    extract_fingerprint,
    is_legacy_fingerprint,
    legacy_model_mismatch,
    verify_history_digest,
)
from intentweave.intent_labeler import IntentLabeler
from intentweave.intent_labels import latest_user_text
from intentweave.models import ProviderResult, ThreadRecord
from intentweave.observatory import emit_intent_label_metric
from intentweave.providers.base import MessageProvider
from intentweave.store.base import ThreadStore

_MODEL_POLICIES = frozenset({"pinned", "routed"})


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
        provider_name: str = "mock",
        intent_labeler: IntentLabeler | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._clock = clock
        self._soft_ttl = soft_ttl_seconds
        self._hard_ttl = hard_ttl_seconds
        self._provider_name = provider_name
        self._intent_labeler = intent_labeler or IntentLabeler()

    def handle_messages(self, body: dict[str, Any]) -> dict[str, Any]:
        thread = body.get("thread")
        if not thread:
            return self._stateless(body)

        thread_type = thread.get("type")
        if thread_type == "create":
            return self._create_thread(body, thread)
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

    def _create_thread(self, body: dict[str, Any], thread: dict[str, Any]) -> dict[str, Any]:
        model = _require_str(body, "model")
        messages = _require_messages(body)
        max_tokens = int(body.get("max_tokens") or 1024)
        model_policy = _resolve_model_policy(thread.get("model_policy"), default="routed")
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
        full_messages = _append_assistant(messages, result, provider_name=self._provider_name)
        fingerprint = attach_history_digest(
            fingerprint,
            system=body.get("system"),
            messages=full_messages,
        )
        record = _record_from_result(
            result=result,
            thread_id=result.response_id,
            parent_response_id=None,
            fingerprint=fingerprint,
            system=body.get("system"),
            tools=body.get("tools"),
            messages=full_messages,
            now=now,
            hard_ttl_seconds=self._hard_ttl,
            provider_name=self._provider_name,
            model_policy=model_policy,
            pinned_model=model if model_policy == "pinned" else None,
        )
        self._store.put(record)
        return self._with_intent_metadata(
            result.as_message_dict(),
            messages=messages,
            model=model,
            resume_pause=False,
        )

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
            if not verify_history_digest(
                parent.fingerprint, system=parent.system, messages=parent.messages
            ):
                raise history_integrity_violation()

            self._assert_model_policy(parent, model)

            stored_fp = parent.fingerprint
            if is_legacy_fingerprint(stored_fp) and legacy_model_mismatch(
                stored_fp, model, self._provider_name
            ):
                pinned = stored_fp.get("model") or parent.pinned_model or parent.model
                raise model_policy_violation(requested_model=model, pinned_model=str(pinned))

            mismatched = diff_fingerprints(stored_fp, incoming_fp)
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
            full_messages = _append_assistant(
                full_messages, result, provider_name=self._provider_name
            )
            child_fp = attach_history_digest(
                dict(parent.fingerprint),
                system=parent.system,
                messages=full_messages,
            )
            # Drop legacy routing keys from stored fingerprint on first routed continue.
            child_fp.pop("model", None)
            child_fp.pop("provider", None)
            if "fingerprint_version" not in child_fp:
                child_fp["fingerprint_version"] = incoming_fp.get("fingerprint_version")

            child = _record_from_result(
                result=result,
                thread_id=parent.thread_id,
                parent_response_id=previous_id,
                fingerprint=child_fp,
                system=parent.system,
                tools=parent.tools,
                messages=full_messages,
                now=now,
                hard_ttl_seconds=self._hard_ttl,
                provider_name=self._provider_name,
                model_policy=parent.model_policy,
                pinned_model=parent.pinned_model,
            )
            self._store.finish_continue(
                previous_id,
                new_record=child,
                mark_parent_continued=True,
            )
            return self._with_intent_metadata(
                result.as_message_dict(),
                messages=new_messages if new_messages else parent.messages,
                model=model,
                resume_pause=parent.paused and not new_messages,
                trace_id=result.response_id,
            )
        except ThreadError:
            self._store.abort_continue(previous_id)
            raise
        except Exception:
            self._store.abort_continue(previous_id)
            raise

    def _assert_model_policy(self, parent: ThreadRecord, requested_model: str) -> None:
        if parent.model_policy != "pinned":
            return
        pinned = parent.pinned_model or parent.model
        if requested_model != pinned:
            raise model_policy_violation(requested_model=requested_model, pinned_model=pinned)

    def _assert_fresh(self, record: ThreadRecord) -> None:
        age = self._clock.now() - record.last_used_epoch
        if age > self._soft_ttl:
            raise thread_not_found("Thread expired (soft TTL).")

    def _assert_continuable(self, record: ThreadRecord) -> None:
        if record.refused:
            raise thread_not_found("Cannot continue after a refusal.")
        if record.stop_reason == "refusal":
            raise thread_not_found("Cannot continue after a refusal.")

    def _with_intent_metadata(
        self,
        message: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        model: str,
        resume_pause: bool,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if not self._intent_labeler.enabled:
            return message

        labeling_messages = list(messages)
        if resume_pause and not latest_user_text(labeling_messages):
            labeling_messages = [{"role": "user", "content": "continue"}]

        labeled = self._intent_labeler.label_thread_turn(
            messages=labeling_messages,
            resume_pause=resume_pause,
        )
        if labeled is None:
            return message

        emit_intent_label_metric(
            trace_id=trace_id or message.get("id"),
            label=labeled.label,
            source=labeled.source,
            confidence=labeled.confidence,
            model=model,
        )
        out = dict(message)
        out["intent_label"] = labeled.label
        out["intent_decision_source"] = labeled.source
        out["intent_confidence"] = round(labeled.confidence, 4)
        return out


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
    provider_name: str,
    model_policy: str,
    pinned_model: str | None,
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
        provider=provider_name,
        model_policy=model_policy,
        pinned_model=pinned_model,
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
    messages: list[dict[str, Any]],
    result: ProviderResult,
    *,
    provider_name: str,
) -> list[dict[str, Any]]:
    out = list(messages)
    out.append(
        {
            "role": "assistant",
            "content": result.content,
            "model": result.model,
            "provider": provider_name,
        }
    )
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


def _resolve_model_policy(value: Any | None, *, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or value not in _MODEL_POLICIES:
        raise invalid_request("thread.model_policy must be 'pinned' or 'routed'.")
    return value
