"""Tests for cryptographic thread forking, PromptWeave context export, and CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intentweave.cli import main as cli_main
from intentweave.cli import verify_thread_db
from intentweave.clock import FakeClock
from intentweave.errors import ThreadError
from intentweave.providers.mock import MockProvider
from intentweave.service import ThreadService
from intentweave.store.memory import MemoryThreadStore
from intentweave.store.sqlite import SQLiteThreadStore


def _create_three_turn_thread(svc: ThreadService, clock: FakeClock) -> tuple[str, list[str]]:
    t0 = svc.handle_messages(
        {
            "model": "mock-local",
            "system": "You are a helpful local assistant.",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Turn 0 question"}],
            "thread": {"type": "create"},
        }
    )
    clock.advance(5.0)
    t1 = svc.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Turn 1 follow-up"}],
            "thread": {"type": "continue", "previous_message_id": t0["id"]},
        }
    )
    clock.advance(5.0)
    t2 = svc.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Turn 2 final"}],
            "thread": {"type": "continue", "previous_message_id": t1["id"]},
        }
    )
    return t0["id"], [t0["id"], t1["id"], t2["id"]]


def test_fork_thread_at_turn_k_preserves_parent_and_lineage_and_can_continue(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "threads.sqlite3"
    clock = FakeClock(1_700_000_000.0)
    store = SQLiteThreadStore(db_path)
    svc = ThreadService(store=store, provider=MockProvider(), clock=clock)

    parent_tid, turn_ids = _create_three_turn_thread(svc, clock)
    turn1_record_before = store.get(turn_ids[1])
    assert turn1_record_before is not None
    expected_parent_digest = turn1_record_before.fingerprint["history_digest"]

    fork_info = svc.fork_thread(parent_tid, new_thread_id="branch_alt", up_to_turn=1)

    assert fork_info["thread_id"] == "branch_alt"
    assert fork_info["turns_copied"] == 2
    assert fork_info["parent_thread_id"] == parent_tid
    assert fork_info["parent_turn"] == 1
    assert fork_info["parent_digest"] == expected_parent_digest
    assert fork_info["head_digest"] == expected_parent_digest

    # Parent thread remains untouched with all 3 turns.
    parent_records = store.list_by_thread(parent_tid)
    assert len(parent_records) == 3

    # Child thread has 2 turns with cryptographic lineage metadata.
    child_records = store.list_by_thread("branch_alt")
    assert len(child_records) == 2
    for rec in child_records:
        assert rec.parent_thread_id == parent_tid
        assert rec.parent_turn == 1
        assert rec.parent_digest == expected_parent_digest

    # Continue the forked branch independently.
    clock.advance(5.0)
    diverged = svc.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Alternative branch turn 2"}],
            "thread": {
                "type": "continue",
                "previous_message_id": fork_info["head_response_id"],
            },
        }
    )
    diverged_rec = store.get(diverged["id"])
    assert diverged_rec is not None
    assert diverged_rec.thread_id == "branch_alt"
    assert diverged_rec.parent_thread_id == parent_tid
    assert diverged_rec.parent_turn == 1
    assert diverged_rec.parent_digest == expected_parent_digest
    store.close()

    # Offline SHA-256 verification passes on both parent and diverged child.
    parent_verify = verify_thread_db(db_path, parent_tid)
    assert parent_verify.valid is True
    assert parent_verify.turns_verified == 3

    child_verify = verify_thread_db(db_path, "branch_alt")
    assert child_verify.valid is True
    assert child_verify.turns_verified == 3


def test_fork_thread_error_cases_and_memory_store() -> None:
    clock = FakeClock(1_700_000_000.0)
    store = MemoryThreadStore()
    svc = ThreadService(store=store, provider=MockProvider(), clock=clock)

    parent_tid, _ = _create_three_turn_thread(svc, clock)

    # Fork works on MemoryThreadStore too.
    info = svc.fork_thread(parent_tid, new_thread_id="mem_fork", up_to_turn=0)
    assert info["turns_copied"] == 1
    assert info["parent_turn"] == 0

    with pytest.raises(ThreadError):
        svc.fork_thread("nonexistent_thread")

    with pytest.raises(ThreadError):
        svc.fork_thread(parent_tid, up_to_turn=99)

    with pytest.raises(ThreadError):
        svc.fork_thread(parent_tid, up_to_turn=-1)

    with pytest.raises(ThreadError):
        svc.fork_thread(parent_tid, new_thread_id="mem_fork")


def test_export_context_blocks_priority_ordering_and_max_turns(tmp_path: Path) -> None:
    db_path = tmp_path / "export.sqlite3"
    clock = FakeClock(1_700_000_000.0)
    store = SQLiteThreadStore(db_path)
    svc = ThreadService(store=store, provider=MockProvider(), clock=clock)

    parent_tid, _ = _create_three_turn_thread(svc, clock)

    # 3 turns = 6 messages (user, assistant, user, assistant, user, assistant).
    all_blocks = svc.export_context_blocks(parent_tid, max_turns=10, base_priority=50)
    assert len(all_blocks) == 6
    assert [b["label"] for b in all_blocks] == [
        "turn_0_user",
        "turn_1_assistant",
        "turn_2_user",
        "turn_3_assistant",
        "turn_4_user",
        "turn_5_assistant",
    ]
    priorities = [b["priority"] for b in all_blocks]
    assert priorities == [50, 51, 52, 53, 54, 55]
    assert all_blocks[0]["content"] == "Turn 0 question"
    assert all_blocks[4]["content"] == "Turn 2 final"
    assert all(isinstance(b["content"], str) and b["content"] for b in all_blocks)

    # Slicing with max_turns=3 returns the 3 most recent messages with increasing priority.
    recent_blocks = svc.export_context_blocks(parent_tid, max_turns=3, base_priority=100)
    assert len(recent_blocks) == 3
    assert [b["label"] for b in recent_blocks] == [
        "turn_3_assistant",
        "turn_4_user",
        "turn_5_assistant",
    ]
    assert [b["priority"] for b in recent_blocks] == [100, 101, 102]
    store.close()


def test_cli_fork_verify_and_export_context(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "cli_threads.sqlite3"
    clock = FakeClock(1_700_000_000.0)
    store = SQLiteThreadStore(db_path)
    svc = ThreadService(store=store, provider=MockProvider(), clock=clock)
    parent_tid, _ = _create_three_turn_thread(svc, clock)
    store.close()

    # CLI fork
    rc = cli_main(
        [
            "fork",
            "--db",
            str(db_path),
            "--thread-id",
            parent_tid,
            "--up-to-turn",
            "1",
            "--new-thread-id",
            "cli_child",
            "--json",
        ]
    )
    assert rc == 0
    fork_out = json.loads(capsys.readouterr().out)
    assert fork_out["thread_id"] == "cli_child"
    assert fork_out["parent_thread_id"] == parent_tid
    assert fork_out["parent_turn"] == 1
    assert fork_out["turns_copied"] == 2
    assert len(fork_out["parent_digest"]) == 64

    # CLI verify on both child and parent
    rc = cli_main(["verify", "--db", str(db_path), "--thread-id", "cli_child", "--json"])
    assert rc == 0
    verify_child = json.loads(capsys.readouterr().out)
    assert verify_child["valid"] is True
    assert verify_child["turns_verified"] == 2

    rc = cli_main(["verify", "--db", str(db_path), "--thread-id", parent_tid, "--json"])
    assert rc == 0
    verify_parent = json.loads(capsys.readouterr().out)
    assert verify_parent["valid"] is True
    assert verify_parent["turns_verified"] == 3

    # CLI export-context
    rc = cli_main(
        [
            "export-context",
            "--db",
            str(db_path),
            "--thread-id",
            "cli_child",
            "--max-turns",
            "4",
        ]
    )
    assert rc == 0
    exported = json.loads(capsys.readouterr().out)
    assert len(exported) == 4
    assert exported[0]["label"] == "turn_0_user"
    assert exported[-1]["label"] == "turn_3_assistant"
    assert exported[-1]["priority"] > exported[0]["priority"]

    # CLI missing thread returns exit code 1
    rc = cli_main(["fork", "--db", str(db_path), "--thread-id", "missing_tid"])
    assert rc == 1
    assert "Error:" in capsys.readouterr().err
