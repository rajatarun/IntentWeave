"""Cryptographic thread branch diffing and cherry-pick turn merging."""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

from intentweave.errors import (
    history_integrity_violation,
    invalid_request,
    thread_not_found,
)
from intentweave.fingerprint import (
    attach_history_digest,
    history_digest,
    verify_history_digest,
)
from intentweave.intent_heuristic import label_heuristic
from intentweave.intent_labels import latest_user_text
from intentweave.models import ThreadRecord
from intentweave.store.sqlite import order_thread_records


def _load_ordered_records(store: Any, thread_id: str) -> list[ThreadRecord]:
    if not hasattr(store, "list_by_thread"):
        raise invalid_request("Configured thread store does not support listing thread records.")
    records = list(store.list_by_thread(thread_id))
    if not records:
        single = store.get(thread_id)
        if single is not None:
            records = list(store.list_by_thread(single.thread_id))
    if not records:
        raise thread_not_found(f"Thread '{thread_id}' not found.")

    ordered = order_thread_records(records)
    for rec in ordered:
        if not verify_history_digest(rec.fingerprint, system=rec.system, messages=rec.messages):
            raise history_integrity_violation()
    return ordered


def _record_digest(rec: ThreadRecord) -> str:
    digest = rec.fingerprint.get("history_digest")
    if isinstance(digest, str) and digest:
        return digest
    return history_digest(system=rec.system, messages=rec.messages)


def _turn_delta_messages(ordered: list[ThreadRecord], turn_index: int) -> list[dict[str, Any]]:
    prev_len = 0 if turn_index == 0 else len(ordered[turn_index - 1].messages)
    return copy.deepcopy(ordered[turn_index].messages[prev_len:])


def _extract_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                else:
                    parts.append(json.dumps(item, sort_keys=True))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _summarize_turn(ordered: list[ThreadRecord], turn_index: int) -> dict[str, Any]:
    rec = ordered[turn_index]
    delta = _turn_delta_messages(ordered, turn_index)
    user_msgs = [m for m in delta if m.get("role") != "assistant"]
    resume_pause = bool(turn_index > 0 and ordered[turn_index - 1].paused and not user_msgs)
    intent_result = label_heuristic(messages=user_msgs, resume_pause=resume_pause)

    assistant_msgs = [m for m in delta if m.get("role") == "assistant"]
    if assistant_msgs:
        assistant_text = _extract_content_text(assistant_msgs[-1].get("content"))
    else:
        assistant_text = _extract_content_text(rec.assistant_message.get("content"))

    return {
        "turn_index": turn_index,
        "response_id": rec.response_id,
        "history_digest": _record_digest(rec),
        "model": rec.model,
        "provider": rec.provider,
        "stop_reason": rec.stop_reason,
        "user_text": latest_user_text(user_msgs),
        "assistant_text": assistant_text,
        "intent_label": intent_result.label,
        "intent_confidence": round(intent_result.confidence, 4),
    }


def _common_prefix_length(ordered_a: list[ThreadRecord], ordered_b: list[ThreadRecord]) -> int:
    common = 0
    for rec_a, rec_b in zip(ordered_a, ordered_b, strict=False):
        if _record_digest(rec_a) == _record_digest(rec_b):
            common += 1
        else:
            break
    return common


def diff_threads(store: Any, thread_a_id: str, thread_b_id: str) -> dict[str, Any]:
    """Compare two thread branches and identify common prefix, diverged turns, and intent shifts."""
    ordered_a = _load_ordered_records(store, thread_a_id)
    ordered_b = _load_ordered_records(store, thread_b_id)

    common_prefix_turns = _common_prefix_length(ordered_a, ordered_b)
    last_common_turn_index = common_prefix_turns - 1 if common_prefix_turns > 0 else None
    last_common_digest = (
        _record_digest(ordered_a[last_common_turn_index])
        if last_common_turn_index is not None
        else None
    )
    baseline_intent = (
        _summarize_turn(ordered_a, last_common_turn_index)["intent_label"]
        if last_common_turn_index is not None
        else None
    )

    only_in_a = [
        _summarize_turn(ordered_a, idx) for idx in range(common_prefix_turns, len(ordered_a))
    ]
    only_in_b = [
        _summarize_turn(ordered_b, idx) for idx in range(common_prefix_turns, len(ordered_b))
    ]

    intent_shifts: list[dict[str, Any]] = []
    max_diverged = max(len(only_in_a), len(only_in_b))
    for offset in range(max_diverged):
        turn_index = common_prefix_turns + offset
        a_turn = only_in_a[offset] if offset < len(only_in_a) else None
        b_turn = only_in_b[offset] if offset < len(only_in_b) else None
        a_label = a_turn["intent_label"] if a_turn is not None else None
        b_label = b_turn["intent_label"] if b_turn is not None else None
        if a_label != b_label:
            intent_shifts.append(
                {
                    "turn_index": turn_index,
                    "thread_a_intent": a_label,
                    "thread_b_intent": b_label,
                    "baseline_intent": baseline_intent,
                }
            )

    return {
        "thread_a_id": ordered_a[0].thread_id,
        "thread_b_id": ordered_b[0].thread_id,
        "thread_a_turns": len(ordered_a),
        "thread_b_turns": len(ordered_b),
        "common_prefix_turns": common_prefix_turns,
        "last_common_turn_index": last_common_turn_index,
        "last_common_digest": last_common_digest,
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "intent_shifts": intent_shifts,
    }


def merge_thread_turns(
    service: Any,
    *,
    source_thread_id: str,
    target_thread_id: str,
    turn_indices: list[int] | None = None,
) -> dict[str, Any]:
    """Append diverged (or selected) turns from ``source_thread_id`` onto ``target_thread_id``.

    Uses the store's normal atomic CAS cryptographic append path (``try_begin_continue`` ->
    ``attach_history_digest`` -> ``finish_continue``), tagging provenance metadata
    (``merged_from_thread_id``, ``source_turn_index``) on every merged turn while keeping
    the target thread's SHA-256 history digest chain 100% valid.
    """
    store = service._store
    ordered_source = _load_ordered_records(store, source_thread_id)
    ordered_target = _load_ordered_records(store, target_thread_id)

    canonical_source_id = ordered_source[0].thread_id
    canonical_target_id = ordered_target[0].thread_id
    if canonical_source_id == canonical_target_id:
        raise invalid_request("source_thread_id and target_thread_id must be distinct threads.")

    if turn_indices is None:
        common_prefix = _common_prefix_length(ordered_source, ordered_target)
        selected_indices = list(range(common_prefix, len(ordered_source)))
    else:
        if not isinstance(turn_indices, list):
            raise invalid_request("turn_indices must be a list of integers.")
        seen_indices: set[int] = set()
        selected_indices = []
        for idx in turn_indices:
            if isinstance(idx, bool) or not isinstance(idx, int):
                raise invalid_request(f"turn_indices must contain integers, got {idx!r}.")
            if idx < 0 or idx >= len(ordered_source):
                raise invalid_request(
                    f"turn index {idx} out of range for source thread "
                    f"(0..{len(ordered_source) - 1})."
                )
            if idx in seen_indices:
                raise invalid_request(f"Duplicate turn index {idx} in turn_indices.")
            seen_indices.add(idx)
            selected_indices.append(idx)

    current_head = ordered_target[-1]
    current_head_id = current_head.response_id
    current_head_digest = _record_digest(current_head)
    merged_response_ids: list[str] = []

    for src_idx in selected_indices:
        src_rec = ordered_source[src_idx]
        delta_messages = _turn_delta_messages(ordered_source, src_idx)
        merge_meta: dict[str, Any] = {
            "merged_from_thread_id": canonical_source_id,
            "source_turn_index": src_idx,
            "source_response_id": src_rec.response_id,
            "source_history_digest": _record_digest(src_rec),
        }

        # Embed provenance metadata into the merged assistant message so it is also
        # cryptographically committed into the target thread's SHA-256 history digest.
        for msg in reversed(delta_messages):
            if msg.get("role") == "assistant":
                existing_meta = (
                    dict(msg["metadata"]) if isinstance(msg.get("metadata"), dict) else {}
                )
                existing_meta["merged_from_thread_id"] = canonical_source_id
                existing_meta["source_turn_index"] = src_idx
                msg["metadata"] = existing_meta
                break

        parent = store.try_begin_continue(current_head_id)
        try:
            if parent.refused or parent.stop_reason == "refusal":
                raise thread_not_found("Cannot merge onto a refused thread.")
            if not verify_history_digest(
                parent.fingerprint, system=parent.system, messages=parent.messages
            ):
                raise history_integrity_violation()

            full_messages = list(parent.messages)
            full_messages.extend(delta_messages)

            now = service._clock.now()
            new_resp_id = f"msg_merge_{uuid.uuid4().hex[:16]}"
            child_fp = attach_history_digest(
                dict(parent.fingerprint),
                system=parent.system,
                messages=full_messages,
            )

            assistant_copy = copy.deepcopy(src_rec.assistant_message)
            if isinstance(assistant_copy, dict):
                assistant_copy["id"] = new_resp_id
                existing_asst_meta = (
                    dict(assistant_copy["metadata"])
                    if isinstance(assistant_copy.get("metadata"), dict)
                    else {}
                )
                existing_asst_meta.update(merge_meta)
                assistant_copy["metadata"] = existing_asst_meta

            child = ThreadRecord(
                response_id=new_resp_id,
                thread_id=parent.thread_id,
                parent_response_id=parent.response_id,
                fingerprint=child_fp,
                system=copy.deepcopy(parent.system),
                tools=copy.deepcopy(parent.tools),
                messages=full_messages,
                model=src_rec.model,
                provider=src_rec.provider,
                model_policy=parent.model_policy,
                pinned_model=parent.pinned_model,
                stop_reason=src_rec.stop_reason,
                assistant_message=assistant_copy,
                continued=False,
                continue_in_flight=False,
                last_used_epoch=now,
                ttl_epoch=int(now) + service._hard_ttl,
                refused=src_rec.refused or src_rec.stop_reason == "refusal",
                paused=src_rec.paused or src_rec.stop_reason == "pause_turn",
                parent_thread_id=parent.parent_thread_id,
                parent_turn=parent.parent_turn,
                parent_digest=parent.parent_digest,
                metadata=merge_meta,
            )
            store.finish_continue(
                parent.response_id,
                new_record=child,
                mark_parent_continued=True,
            )
            current_head_id = new_resp_id
            current_head_digest = child_fp["history_digest"]
            merged_response_ids.append(new_resp_id)
        except Exception:
            store.abort_continue(parent.response_id)
            raise

    return {
        "merged_count": len(merged_response_ids),
        "source_thread_id": canonical_source_id,
        "target_thread_id": canonical_target_id,
        "head_response_id": current_head_id,
        "new_head_digest": current_head_digest,
        "merged_response_ids": merged_response_ids,
    }
