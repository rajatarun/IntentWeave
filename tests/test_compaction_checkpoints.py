"""Tests for cryptographic compaction checkpoints, context export, and CLI."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from intentweave.cli import main as cli_main
from intentweave.cli import verify_thread_db
from intentweave.clock import FakeClock
from intentweave.compaction import verify_checkpoint
from intentweave.errors import ThreadError
from intentweave.providers.mock import MockProvider
from intentweave.service import ThreadService
from intentweave.store.memory import MemoryThreadStore
from intentweave.store.sqlite import SQLiteThreadStore, order_thread_records


def _create_four_turn_thread(svc: ThreadService, clock: FakeClock) -> tuple[str, list[str]]:
    t0 = svc.handle_messages(
        {
            "model": "mock-local",
            "system": "You are a helpful edge assistant.",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Turn 0 initial prompt"}],
            "thread": {"type": "create"},
        }
    )
    clock.advance(5.0)
    t1 = svc.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Turn 1 details"}],
            "thread": {"type": "continue", "previous_message_id": t0["id"]},
        }
    )
    clock.advance(5.0)
    t2 = svc.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Turn 2 follow-up"}],
            "thread": {"type": "continue", "previous_message_id": t1["id"]},
        }
    )
    clock.advance(5.0)
    t3 = svc.handle_messages(
        {
            "model": "mock-local",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Turn 3 latest"}],
            "thread": {"type": "continue", "previous_message_id": t2["id"]},
        }
    )
    return t0["id"], [t0["id"], t1["id"], t2["id"], t3["id"]]


def test_create_checkpoint_persists_valid_digest_and_preserves_thread_verification(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "compaction.sqlite3"
    clock = FakeClock(1_700_000_000.0)
    store = SQLiteThreadStore(db_path)
    svc = ThreadService(store=store, provider=MockProvider(), clock=clock)

    thread_id, turn_ids = _create_four_turn_thread(svc, clock)
    turn1_rec = store.get(turn_ids[1])
    assert turn1_rec is not None
    expected_digest = turn1_rec.fingerprint["history_digest"]

    ckpt = svc.create_checkpoint(
        thread_id,
        summary_text="Turns 0-1 established the user's goal and initial details.",
        up_to_turn=1,
    )

    assert ckpt["checkpoint_id"].startswith("ckpt_")
    assert ckpt["thread_id"] == thread_id
    assert ckpt["up_to_turn"] == 1
    assert ckpt["covered_digest"] == expected_digest
    assert ckpt["summary_text"] == "Turns 0-1 established the user's goal and initial details."
    assert isinstance(ckpt["created_at"], str) and ckpt["created_at"]

    # Verify persistence directly in SQLite WAL table with required schema columns.
    conn = sqlite3.connect(str(db_path))
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(journal_mode).lower() == "wal"
        row = conn.execute(
            """
            SELECT checkpoint_id, thread_id, up_to_turn, covered_digest, summary_text, created_at
            FROM thread_checkpoints
            WHERE checkpoint_id = ?
            """,
            (ckpt["checkpoint_id"],),
        ).fetchone()
        assert row is not None
        assert row[0] == ckpt["checkpoint_id"]
        assert row[1] == thread_id
        assert row[2] == 1
        assert row[3] == expected_digest
        assert row[4] == ckpt["summary_text"]
        assert row[5] == ckpt["created_at"]
    finally:
        conn.close()

    ordered = order_thread_records(store.list_by_thread(thread_id))
    assert verify_checkpoint(ckpt, ordered) is True

    # Reopen store from disk and confirm checkpoint is still present.
    store.close()
    reopened = SQLiteThreadStore(db_path)
    try:
        latest = reopened.get_latest_checkpoint(thread_id)
        assert latest == ckpt
        assert reopened.list_checkpoints(thread_id) == [ckpt]
    finally:
        reopened.close()

    # Full-thread offline verification must still pass cleanly.
    verify_result = verify_thread_db(db_path, thread_id)
    assert verify_result.valid is True
    assert verify_result.turns_verified == 4


def test_export_context_blocks_from_checkpoint_emits_summary_and_post_turns_only(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "export_ckpt.sqlite3"
    clock = FakeClock(1_700_000_000.0)
    store = SQLiteThreadStore(db_path)
    svc = ThreadService(store=store, provider=MockProvider(), clock=clock)

    thread_id, _ = _create_four_turn_thread(svc, clock)

    # Without a checkpoint, from_checkpoint=True falls back to standard export.
    no_ckpt_blocks = svc.export_context_blocks(
        thread_id, max_turns=10, base_priority=50, from_checkpoint=True
    )
    assert len(no_ckpt_blocks) == 8
    assert no_ckpt_blocks[0]["label"] == "turn_0_user"

    # Create checkpoint covering turns 0..1 (messages 0..3).
    summary = "Compacted summary of turns 0 and 1."
    svc.create_checkpoint(thread_id, summary_text=summary, up_to_turn=1)

    # Default from_checkpoint=False still returns full recent turns without summary.
    default_blocks = svc.export_context_blocks(thread_id, max_turns=10, base_priority=50)
    assert len(default_blocks) == 8
    assert all(b["label"] != "checkpoint_summary" for b in default_blocks)

    # from_checkpoint=True emits summary + turns strictly after turn 1 (messages 4..7).
    compacted = svc.export_context_blocks(
        thread_id, max_turns=10, base_priority=50, from_checkpoint=True
    )
    assert [b["label"] for b in compacted] == [
        "checkpoint_summary",
        "turn_4_user",
        "turn_5_assistant",
        "turn_6_user",
        "turn_7_assistant",
    ]
    assert compacted[0]["content"] == summary
    assert compacted[1]["content"] == "Turn 2 follow-up"
    assert compacted[3]["content"] == "Turn 3 latest"

    # Summary block must have higher priority than all post-checkpoint turn blocks.
    turn_priorities = [b["priority"] for b in compacted[1:]]
    assert turn_priorities == [50, 51, 52, 53]
    assert compacted[0]["priority"] > max(turn_priorities)

    # max_turns limits post-checkpoint messages while always retaining checkpoint_summary.
    trimmed = svc.export_context_blocks(
        thread_id, max_turns=2, base_priority=80, from_checkpoint=True
    )
    assert [b["label"] for b in trimmed] == [
        "checkpoint_summary",
        "turn_6_user",
        "turn_7_assistant",
    ]
    assert [b["priority"] for b in trimmed[1:]] == [80, 81]
    assert trimmed[0]["priority"] > 81

    # Adding a newer checkpoint covering the latest turn (up_to_turn=None -> turn 3)
    # emits only the checkpoint_summary block until new turns arrive.
    latest_ckpt = svc.create_checkpoint(thread_id, summary_text="Summary through turn 3.")
    assert latest_ckpt["up_to_turn"] == 3
    only_summary = svc.export_context_blocks(
        thread_id, max_turns=10, base_priority=50, from_checkpoint=True
    )
    assert len(only_summary) == 1
    assert only_summary[0]["label"] == "checkpoint_summary"
    assert only_summary[0]["content"] == "Summary through turn 3."
    assert only_summary[0]["priority"] > 50
    store.close()


def test_checkpoint_tamper_detection_and_validation_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "tamper.sqlite3"
    clock = FakeClock(1_700_000_000.0)
    store = SQLiteThreadStore(db_path)
    svc = ThreadService(store=store, provider=MockProvider(), clock=clock)

    thread_id, _ = _create_four_turn_thread(svc, clock)
    ckpt = svc.create_checkpoint(thread_id, summary_text="Valid summary", up_to_turn=1)

    # Validation error cases.
    with pytest.raises(ThreadError):
        svc.create_checkpoint("nonexistent_thread", summary_text="Summary")
    with pytest.raises(ThreadError):
        svc.create_checkpoint(thread_id, summary_text="   ")
    with pytest.raises(ThreadError):
        svc.create_checkpoint(thread_id, summary_text="Summary", up_to_turn=-1)
    with pytest.raises(ThreadError):
        svc.create_checkpoint(thread_id, summary_text="Summary", up_to_turn=99)

    # Tamper with covered_digest directly in SQLite.
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE thread_checkpoints SET covered_digest = ? WHERE checkpoint_id = ?",
            ("0" * 64, ckpt["checkpoint_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    tampered = store.get_latest_checkpoint(thread_id)
    assert tampered is not None
    ordered = order_thread_records(store.list_by_thread(thread_id))
    assert verify_checkpoint(tampered, ordered) is False

    with pytest.raises(ThreadError):
        svc.export_context_blocks(thread_id, from_checkpoint=True)
    store.close()


def test_checkpoint_works_with_memory_thread_store() -> None:
    clock = FakeClock(1_700_000_000.0)
    store = MemoryThreadStore()
    svc = ThreadService(store=store, provider=MockProvider(), clock=clock)

    thread_id, _ = _create_four_turn_thread(svc, clock)
    ckpt = svc.create_checkpoint(thread_id, summary_text="Memory store summary", up_to_turn=2)
    assert ckpt["up_to_turn"] == 2
    assert len(ckpt["covered_digest"]) == 64

    blocks = svc.export_context_blocks(thread_id, from_checkpoint=True)
    assert [b["label"] for b in blocks] == [
        "checkpoint_summary",
        "turn_6_user",
        "turn_7_assistant",
    ]
    assert blocks[0]["content"] == "Memory store summary"


def test_cli_checkpoint_verify_and_export_context_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "cli_ckpt.sqlite3"
    clock = FakeClock(1_700_000_000.0)
    store = SQLiteThreadStore(db_path)
    svc = ThreadService(store=store, provider=MockProvider(), clock=clock)
    thread_id, turn_ids = _create_four_turn_thread(svc, clock)
    turn1_rec = store.get(turn_ids[1])
    assert turn1_rec is not None
    expected_digest = turn1_rec.fingerprint["history_digest"]
    store.close()

    # CLI checkpoint with --json and explicit --up-to-turn
    rc = cli_main(
        [
            "checkpoint",
            "--db",
            str(db_path),
            "--thread-id",
            thread_id,
            "--summary",
            "CLI compacted summary up to turn 1.",
            "--up-to-turn",
            "1",
            "--json",
        ]
    )
    assert rc == 0
    ckpt_out = json.loads(capsys.readouterr().out)
    assert ckpt_out["thread_id"] == thread_id
    assert ckpt_out["up_to_turn"] == 1
    assert ckpt_out["covered_digest"] == expected_digest
    assert ckpt_out["summary_text"] == "CLI compacted summary up to turn 1."

    # CLI verify still passes on the full 4-turn thread
    rc = cli_main(["verify", "--db", str(db_path), "--thread-id", thread_id, "--json"])
    assert rc == 0
    verify_out = json.loads(capsys.readouterr().out)
    assert verify_out["valid"] is True
    assert verify_out["turns_verified"] == 4

    # CLI export-context --from-checkpoint returns summary + post-checkpoint turns only
    rc = cli_main(
        [
            "export-context",
            "--db",
            str(db_path),
            "--thread-id",
            thread_id,
            "--from-checkpoint",
        ]
    )
    assert rc == 0
    exported = json.loads(capsys.readouterr().out)
    assert [b["label"] for b in exported] == [
        "checkpoint_summary",
        "turn_4_user",
        "turn_5_assistant",
        "turn_6_user",
        "turn_7_assistant",
    ]
    assert exported[0]["content"] == "CLI compacted summary up to turn 1."

    # CLI checkpoint human-readable output (default up_to_turn -> latest turn)
    rc = cli_main(
        [
            "checkpoint",
            "--db",
            str(db_path),
            "--thread-id",
            thread_id,
            "--summary",
            "Full thread summary.",
        ]
    )
    assert rc == 0
    human_out = capsys.readouterr().out
    assert "CHECKPOINT:" in human_out
    assert "up_to_turn=3" in human_out

    # CLI error handling: missing thread & missing DB
    rc = cli_main(
        [
            "checkpoint",
            "--db",
            str(db_path),
            "--thread-id",
            "missing_thread",
            "--summary",
            "Nope",
        ]
    )
    assert rc == 1
    assert "Error:" in capsys.readouterr().err

    rc = cli_main(
        [
            "checkpoint",
            "--db",
            str(tmp_path / "does_not_exist.sqlite3"),
            "--thread-id",
            thread_id,
            "--summary",
            "Nope",
        ]
    )
    assert rc == 1
    assert "Error:" in capsys.readouterr().err
