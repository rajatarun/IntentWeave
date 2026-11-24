"""Tests for IntentWeave verified portable thread bundle export/import and CLI."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from intentweave.bundle import (
    NODE_SNAPSHOT_SCHEMA,
    export_thread_bundle,
    import_thread_bundle,
)
from intentweave.cli import main as cli_main
from intentweave.fingerprint import attach_history_digest
from intentweave.models import ThreadRecord
from intentweave.store.sqlite import SQLiteThreadStore

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _seed_thread(store: SQLiteThreadStore, thread_id: str = "thr-alpha") -> None:
    system = "You are a helpful local agent."
    m0 = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    rec0 = ThreadRecord(
        response_id=f"{thread_id}_r0",
        thread_id=thread_id,
        parent_response_id=None,
        fingerprint=attach_history_digest({}, system=system, messages=m0),
        system=system,
        tools=None,
        messages=m0,
        model="local-qwen",
        stop_reason="end_turn",
        assistant_message={"id": f"{thread_id}_r0", "role": "assistant", "content": "Hi there!"},
        continued=True,
        parent_thread_id="thr-root-origin",
        parent_turn=0,
        parent_digest="a" * 64,
    )
    m1 = [
        *m0,
        {"role": "user", "content": "Summarize status"},
        {"role": "assistant", "content": "All systems nominal."},
    ]
    rec1 = ThreadRecord(
        response_id=f"{thread_id}_r1",
        thread_id=thread_id,
        parent_response_id=rec0.response_id,
        fingerprint=attach_history_digest({}, system=system, messages=m1),
        system=system,
        tools=None,
        messages=m1,
        model="local-qwen",
        stop_reason="end_turn",
        assistant_message={
            "id": f"{thread_id}_r1",
            "role": "assistant",
            "content": "All systems nominal.",
        },
        continued=False,
    )
    store.put(rec0)
    store.put(rec1)
    store.create_checkpoint(
        thread_id,
        summary_text="Greeted user and confirmed status",
        up_to_turn=0,
    )


def test_export_import_roundtrip_preserves_turns_lineage_and_checkpoints(tmp_path: Path) -> None:
    src = SQLiteThreadStore(tmp_path / "src.db")
    _seed_thread(src, "thr-migrate")

    out_dir = tmp_path / "bundle_out"
    manifest = export_thread_bundle(src, "thr-migrate", out_dir, node_id="pi-home-1")
    src.close()

    assert manifest["schema"] == NODE_SNAPSHOT_SCHEMA
    assert manifest["node_id"] == "pi-home-1"
    assert _SHA256_RE.match(manifest["checksum_sha256"])
    assert len(manifest["components"]) == 1
    comp = manifest["components"][0]
    assert comp["kind"] == "json_bundle"
    assert comp["encrypted"] is False
    assert _SHA256_RE.match(comp["sha256"])

    dst = SQLiteThreadStore(tmp_path / "dst.db")
    try:
        summary = import_thread_bundle(out_dir / "snapshot-manifest.json", dst)
        assert summary["thread_id"] == "thr-migrate"
        assert summary["turns_imported"] == 2
        assert summary["checkpoints_imported"] == 1
        assert summary["fork_parent"]["parent_thread_id"] == "thr-root-origin"

        imported_turns = dst.list_by_thread("thr-migrate")
        assert len(imported_turns) == 2
        imported_ckpts = dst.list_checkpoints("thr-migrate")
        assert len(imported_ckpts) == 1
        assert imported_ckpts[0]["summary_text"] == "Greeted user and confirmed status"
    finally:
        dst.close()


def test_tampered_turn_content_rejected_without_partial_writes(tmp_path: Path) -> None:
    src = SQLiteThreadStore(tmp_path / "src.db")
    _seed_thread(src, "thr-tamper")
    out_dir = tmp_path / "out"
    manifest = export_thread_bundle(src, "thr-tamper", out_dir, node_id="node-1")
    src.close()

    bundle_path = out_dir / manifest["components"][0]["relative_path"]
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    # Mutate turn message AND recompute manifest SHA-256 to prove history_digest check catches it.
    bundle["turns"][1]["messages"][-1]["content"] = "INJECTED MALICIOUS CONTENT"
    new_bytes = json.dumps(bundle, sort_keys=True, indent=2).encode("utf-8")
    bundle_path.write_bytes(new_bytes)
    manifest["components"][0]["sha256"] = hashlib.sha256(new_bytes).hexdigest()
    manifest["components"][0]["size_bytes"] = len(new_bytes)
    manifest["checksum_sha256"] = hashlib.sha256(
        json.dumps(manifest["components"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    (out_dir / "snapshot-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    dst = SQLiteThreadStore(tmp_path / "dst.db")
    try:
        with pytest.raises(ValueError, match="history_digest mismatch"):
            import_thread_bundle(out_dir / "snapshot-manifest.json", dst)
        assert dst.list_by_thread("thr-tamper") == []
        assert dst.list_checkpoints("thr-tamper") == []
    finally:
        dst.close()


def test_broken_checkpoint_chain_rejected_without_partial_writes(tmp_path: Path) -> None:
    src = SQLiteThreadStore(tmp_path / "src.db")
    _seed_thread(src, "thr-ckpt")
    out_dir = tmp_path / "out"
    manifest = export_thread_bundle(src, "thr-ckpt", out_dir, node_id="node-1")
    src.close()

    bundle_path = out_dir / manifest["components"][0]["relative_path"]
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["checkpoints"][0]["covered_digest"] = "f" * 64
    new_bytes = json.dumps(bundle, sort_keys=True, indent=2).encode("utf-8")
    bundle_path.write_bytes(new_bytes)
    manifest["components"][0]["sha256"] = hashlib.sha256(new_bytes).hexdigest()
    manifest["components"][0]["size_bytes"] = len(new_bytes)
    manifest["checksum_sha256"] = hashlib.sha256(
        json.dumps(manifest["components"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    (out_dir / "snapshot-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    dst = SQLiteThreadStore(tmp_path / "dst.db")
    try:
        with pytest.raises(ValueError, match="failed cryptographic chain verification"):
            import_thread_bundle(out_dir / "snapshot-manifest.json", dst)
        assert dst.list_by_thread("thr-ckpt") == []
        assert dst.list_checkpoints("thr-ckpt") == []
    finally:
        dst.close()


def test_cli_export_and_import_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src_db = tmp_path / "cli_src.db"
    src = SQLiteThreadStore(src_db)
    _seed_thread(src, "thr-cli")
    src.close()

    out_dir = tmp_path / "cli_bundle"
    rc_exp = cli_main(
        [
            "export-bundle",
            "--db",
            str(src_db),
            "--thread-id",
            "thr-cli",
            "--out",
            str(out_dir),
            "--node-id",
            "cli-node",
            "--json",
        ]
    )
    assert rc_exp == 0
    exp_payload = json.loads(capsys.readouterr().out)
    assert exp_payload["schema"] == NODE_SNAPSHOT_SCHEMA

    dst_db = tmp_path / "cli_dst.db"
    rc_imp = cli_main(
        [
            "import-bundle",
            "--db",
            str(dst_db),
            "--manifest",
            str(out_dir / "snapshot-manifest.json"),
            "--json",
        ]
    )
    assert rc_imp == 0
    imp_payload = json.loads(capsys.readouterr().out)
    assert imp_payload["thread_id"] == "thr-cli"
    assert imp_payload["turns_imported"] == 2
    assert imp_payload["checkpoints_imported"] == 1
