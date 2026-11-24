"""Tests for Cycle 4 cryptographic thread branch diffing, cherry-pick merge, and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intentweave.cli import main as cli_main
from intentweave.cli import verify_thread_db
from intentweave.clock import FakeClock
from intentweave.errors import ThreadError
from intentweave.merge import diff_threads, merge_thread_turns
from intentweave.providers.mock import MockProvider
from intentweave.service import ThreadService
from intentweave.store.sqlite import SQLiteThreadStore, order_thread_records


def _seed_diverged_threads(
    tmp_path: Path,
) -> tuple[Path, SQLiteThreadStore, ThreadService, FakeClock, str, str]:
    db_path = tmp_path / "threads.sqlite3"
    clock = FakeClock(1_700_000_000.0)
    store = SQLiteThreadStore(db_path)
    svc = ThreadService(store=store, provider=MockProvider(), clock=clock)

    # Shared prefix: turns 0 and 1
    t0 = svc.handle_messages(
        {
            "model": "mock-local",
            "system": "You are a helpful edge planner.",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Help me plan a weekend trip."}],
            "thread": {"type": "create"},
        }
    )
    clock.advance(5.0)
    t1 = svc.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Let's compare coastal towns."}],
            "thread": {"type": "continue", "previous_message_id": t0["id"]},
        }
    )
    thread_a_id = t0["id"]

    # Fork at turn 1 into thread_b
    fork_summary = store.fork_thread(thread_a_id, new_thread_id="fork_branch_b", up_to_turn=1)
    thread_b_id = fork_summary["thread_id"]
    fork_head = fork_summary["head_response_id"]

    # Continue thread A with turn 2
    clock.advance(5.0)
    svc.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Draft an itinerary for Monterey."}],
            "thread": {"type": "continue", "previous_message_id": t1["id"]},
        }
    )

    # Continue thread B with two diverged turns (turns 2 and 3)
    clock.advance(5.0)
    b2 = svc.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [
                {"role": "user", "content": "Actually, debug this Python traceback error instead."}
            ],
            "thread": {"type": "continue", "previous_message_id": fork_head},
        }
    )
    clock.advance(5.0)
    svc.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Summarize the fix in two bullet points."}],
            "thread": {"type": "continue", "previous_message_id": b2["id"]},
        }
    )

    return db_path, store, svc, clock, thread_a_id, thread_b_id


def test_diff_threads_identifies_common_prefix_and_diverged_turns(tmp_path: Path) -> None:
    _, store, svc, _, thread_a_id, thread_b_id = _seed_diverged_threads(tmp_path)
    try:
        diff = diff_threads(store, thread_a_id, thread_b_id)
        svc_diff = svc.diff_threads(thread_a_id, thread_b_id)
        assert diff == svc_diff

        assert diff["thread_a_id"] == thread_a_id
        assert diff["thread_b_id"] == thread_b_id
        assert diff["thread_a_turns"] == 3
        assert diff["thread_b_turns"] == 4
        assert diff["common_prefix_turns"] == 2
        assert diff["last_common_turn_index"] == 1
        assert isinstance(diff["last_common_digest"], str)
        assert len(diff["last_common_digest"]) == 64

        assert len(diff["only_in_a"]) == 1
        assert diff["only_in_a"][0]["turn_index"] == 2
        assert "Monterey" in diff["only_in_a"][0]["user_text"]

        assert len(diff["only_in_b"]) == 2
        assert [t["turn_index"] for t in diff["only_in_b"]] == [2, 3]
        assert "traceback" in diff["only_in_b"][0]["user_text"]
        assert "two bullet points" in diff["only_in_b"][1]["user_text"]
        assert isinstance(diff["intent_shifts"], list)
    finally:
        store.close()


def test_merge_thread_turns_preserves_hash_chain_and_provenance(tmp_path: Path) -> None:
    db_path, store, svc, _, thread_a_id, thread_b_id = _seed_diverged_threads(tmp_path)
    try:
        # Cherry-pick turn 3 from branch B onto branch A
        result = svc.merge_thread_turns(
            source_thread_id=thread_b_id,
            target_thread_id=thread_a_id,
            turn_indices=[3],
        )
        assert result["merged_count"] == 1
        assert result["source_thread_id"] == thread_b_id
        assert result["target_thread_id"] == thread_a_id
        assert isinstance(result["new_head_digest"], str)
        assert len(result["new_head_digest"]) == 64

        ordered_a = order_thread_records(store.list_by_thread(thread_a_id))
        assert len(ordered_a) == 4
        merged_rec = ordered_a[-1]
        assert merged_rec.metadata["merged_from_thread_id"] == thread_b_id
        assert merged_rec.metadata["source_turn_index"] == 3
        assert merged_rec.fingerprint["history_digest"] == result["new_head_digest"]
    finally:
        store.close()

    # Offline SHA-256 chain verification must remain 100% valid
    verification = verify_thread_db(db_path, thread_a_id)
    assert verification.valid is True
    assert verification.turns_verified == 4
    assert verification.errors == []


def test_merge_thread_turns_default_merges_all_diverged_and_rejects_self_merge(
    tmp_path: Path,
) -> None:
    db_path, store, svc, _, thread_a_id, thread_b_id = _seed_diverged_threads(tmp_path)
    try:
        with pytest.raises(ThreadError) as exc_info:
            merge_thread_turns(
                svc,
                source_thread_id=thread_a_id,
                target_thread_id=thread_a_id,
            )
        assert "distinct" in exc_info.value.message

        res = merge_thread_turns(
            svc,
            source_thread_id=thread_b_id,
            target_thread_id=thread_a_id,
        )
        assert res["merged_count"] == 2
        assert len(res["merged_response_ids"]) == 2
    finally:
        store.close()

    verification = verify_thread_db(db_path, thread_a_id)
    assert verification.valid is True
    assert verification.turns_verified == 5


def test_cli_diff_threads_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path, store, _, _, thread_a_id, thread_b_id = _seed_diverged_threads(tmp_path)
    store.close()

    rc = cli_main(
        [
            "diff-threads",
            "--db",
            str(db_path),
            "--thread-a",
            thread_a_id,
            "--thread-b",
            thread_b_id,
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["thread_a_id"] == thread_a_id
    assert payload["thread_b_id"] == thread_b_id
    assert payload["common_prefix_turns"] == 2
    assert len(payload["only_in_a"]) == 1
    assert len(payload["only_in_b"]) == 2
