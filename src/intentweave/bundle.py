"""Verified portable thread bundle export/import (node-snapshot-v1 compatible)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from intentweave.compaction import ThreadCheckpoint, verify_checkpoint
from intentweave.errors import history_integrity_violation, thread_not_found
from intentweave.fingerprint import history_digest
from intentweave.models import ThreadRecord
from intentweave.store.sqlite import order_thread_records

NODE_SNAPSHOT_SCHEMA = "node-snapshot-v1"
_BUNDLE_FORMAT = "intentweave-thread-bundle-v1"


def _compute_components_checksum(components: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        components,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _safe_bundle_filename(thread_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in thread_id)
    safe = safe.strip(".") or "thread"
    return f"{safe}.bundle.json"


def _validate_records_chain(thread_id: str, ordered: list[ThreadRecord]) -> None:
    if not ordered:
        raise ValueError(f"Bundle for thread '{thread_id}' contains no turns")

    by_id: dict[str, ThreadRecord] = {}
    for idx, rec in enumerate(ordered):
        if rec.thread_id != thread_id:
            raise ValueError(
                f"Turn '{rec.response_id}' thread_id '{rec.thread_id}' "
                f"does not match bundle thread_id '{thread_id}'"
            )
        expected_digest = rec.fingerprint.get("history_digest")
        if not expected_digest:
            raise ValueError(f"Turn '{rec.response_id}' is missing history_digest")
        actual_digest = history_digest(system=rec.system, messages=rec.messages)
        if actual_digest != expected_digest:
            raise ValueError(
                f"Turn '{rec.response_id}' history_digest mismatch "
                f"(expected {expected_digest}, got {actual_digest})"
            )
        if idx == 0:
            if rec.parent_response_id is not None:
                raise ValueError("Root turn must have parent_response_id=None")
        else:
            prev = ordered[idx - 1]
            if rec.parent_response_id != prev.response_id:
                raise ValueError(
                    f"Turn '{rec.response_id}' parent_response_id "
                    f"'{rec.parent_response_id}' does not match '{prev.response_id}'"
                )
            if rec.system != prev.system:
                raise ValueError(
                    f"Turn '{rec.response_id}' system prompt differs from "
                    f"parent '{prev.response_id}'"
                )
            if rec.messages[: len(prev.messages)] != prev.messages:
                raise ValueError(
                    f"Turn '{rec.response_id}' does not preserve parent '{prev.response_id}' prefix"
                )
        by_id[rec.response_id] = rec


def export_thread_bundle(
    store: Any,
    thread_id: str,
    output_dir: str | Path,
    *,
    node_id: str,
) -> dict[str, Any]:
    """Export thread turns, fork lineage, and checkpoints into a ``node-snapshot-v1`` bundle."""
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("'thread_id' must be a non-empty string")
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("'node_id' must be a non-empty string")

    records = store.list_by_thread(thread_id)
    resolved_tid = thread_id
    if not records:
        single = store.get(thread_id)
        if single is not None:
            resolved_tid = single.thread_id
            records = store.list_by_thread(resolved_tid)
    if not records:
        raise thread_not_found(f"Thread '{thread_id}' not found.")

    ordered = order_thread_records(records)
    try:
        _validate_records_chain(resolved_tid, ordered)
    except ValueError as exc:
        raise history_integrity_violation() from exc

    raw_checkpoints: list[dict[str, Any]] = []
    if hasattr(store, "list_checkpoints"):
        raw_checkpoints = list(store.list_checkpoints(resolved_tid))
    for ckpt in raw_checkpoints:
        if not verify_checkpoint(ckpt, ordered):
            raise history_integrity_violation()

    root = ordered[0]
    bundle_payload: dict[str, Any] = {
        "format": _BUNDLE_FORMAT,
        "thread_id": resolved_tid,
        "node_id": node_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "fork_parent": {
            "parent_thread_id": root.parent_thread_id,
            "parent_turn": root.parent_turn,
            "parent_digest": root.parent_digest,
        },
        "turns": [rec.to_item() for rec in ordered],
        "checkpoints": raw_checkpoints,
    }

    bundle_bytes = (
        json.dumps(bundle_payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    bundle_sha256 = hashlib.sha256(bundle_bytes).hexdigest()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_filename = _safe_bundle_filename(resolved_tid)
    (out_dir / bundle_filename).write_bytes(bundle_bytes)

    components: list[dict[str, Any]] = [
        {
            "name": "intent_threads",
            "kind": "json_bundle",
            "relative_path": bundle_filename,
            "sha256": bundle_sha256,
            "size_bytes": len(bundle_bytes),
            "encrypted": False,
        }
    ]
    checksum_sha256 = _compute_components_checksum(components)

    manifest: dict[str, Any] = {
        "schema": NODE_SNAPSHOT_SCHEMA,
        "snapshot_id": f"snap_{uuid.uuid4().hex[:16]}",
        "node_id": node_id,
        "created_at": datetime.now(UTC).isoformat(),
        "components": components,
        "checksum_sha256": checksum_sha256,
    }

    (out_dir / "snapshot-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def import_thread_bundle(
    manifest_path: str | Path,
    store: Any,
) -> dict[str, Any]:
    """Verify ``node-snapshot-v1`` bundle SHA-256, turn digest chain, and checkpoints
    fail-closed before importing into ``store``.
    """
    mpath = Path(manifest_path)
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read snapshot manifest: {exc}") from exc

    if not isinstance(manifest, dict):
        raise ValueError("Snapshot manifest root must be a JSON object")
    if manifest.get("schema") != NODE_SNAPSHOT_SCHEMA:
        raise ValueError(
            f"Unsupported snapshot schema {manifest.get('schema')!r}; "
            f"expected {NODE_SNAPSHOT_SCHEMA!r}"
        )

    components = manifest.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("Snapshot manifest 'components' must be a non-empty list")

    recorded_checksum = manifest.get("checksum_sha256")
    expected_checksum = _compute_components_checksum(components)
    if not isinstance(recorded_checksum, str) or recorded_checksum != expected_checksum:
        raise ValueError(
            "Snapshot manifest checksum_sha256 mismatch "
            f"(expected {expected_checksum}, got {recorded_checksum!r})"
        )

    bundle_components = [
        c for c in components if isinstance(c, dict) and c.get("kind") == "json_bundle"
    ]
    if len(bundle_components) != 1:
        raise ValueError("Snapshot manifest must contain exactly one 'json_bundle' component")

    comp = bundle_components[0]
    rel_path = comp.get("relative_path")
    if not isinstance(rel_path, str) or not rel_path:
        raise ValueError("Bundle component missing valid 'relative_path'")

    base_dir = mpath.parent.resolve()
    bundle_path = (base_dir / rel_path).resolve()
    if base_dir not in bundle_path.parents and bundle_path != base_dir:
        raise ValueError("Bundle component relative_path escapes manifest directory")
    if not bundle_path.is_file():
        raise ValueError(f"Bundle file not found: {bundle_path}")

    bundle_bytes = bundle_path.read_bytes()
    actual_sha = hashlib.sha256(bundle_bytes).hexdigest()
    if actual_sha != comp.get("sha256"):
        raise ValueError(
            f"Bundle SHA-256 mismatch (expected {comp.get('sha256')!r}, got {actual_sha})"
        )
    if len(bundle_bytes) != comp.get("size_bytes"):
        raise ValueError(
            f"Bundle size_bytes mismatch (expected {comp.get('size_bytes')!r}, "
            f"got {len(bundle_bytes)})"
        )

    try:
        bundle = json.loads(bundle_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid bundle JSON: {exc}") from exc

    if not isinstance(bundle, dict) or bundle.get("format") != _BUNDLE_FORMAT:
        raise ValueError("Unexpected thread bundle format")

    thread_id = bundle.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("Bundle missing valid 'thread_id'")

    raw_turns = bundle.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ValueError("Bundle 'turns' must be a non-empty list")

    try:
        records = [ThreadRecord.from_item(item) for item in raw_turns]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Malformed turn record in bundle: {exc}") from exc

    try:
        ordered = order_thread_records(records)
    except Exception as exc:
        raise ValueError(f"Invalid turn parent chain in bundle: {exc}") from exc

    _validate_records_chain(thread_id, ordered)

    raw_checkpoints = bundle.get("checkpoints", [])
    if not isinstance(raw_checkpoints, list):
        raise ValueError("Bundle 'checkpoints' must be a list")

    validated_checkpoints: list[ThreadCheckpoint] = []
    for raw_ckpt in raw_checkpoints:
        if not isinstance(raw_ckpt, dict):
            raise ValueError("Bundle checkpoint entry must be a JSON object")
        try:
            ckpt = ThreadCheckpoint.from_dict(raw_ckpt)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Malformed checkpoint in bundle: {exc}") from exc
        if ckpt.thread_id != thread_id or not verify_checkpoint(ckpt, ordered):
            raise ValueError(
                f"Checkpoint '{ckpt.checkpoint_id}' failed cryptographic chain verification"
            )
        validated_checkpoints.append(ckpt)

    # All cryptographic checks passed — commit into store.
    for rec in ordered:
        store.put(rec)
    if validated_checkpoints and hasattr(store, "put_checkpoint"):
        for ckpt in validated_checkpoints:
            store.put_checkpoint(ckpt.to_dict())

    return {
        "snapshot_id": manifest["snapshot_id"],
        "node_id": manifest["node_id"],
        "thread_id": thread_id,
        "turns_imported": len(ordered),
        "checkpoints_imported": len(validated_checkpoints),
        "fork_parent": bundle.get("fork_parent"),
    }
