"""Offline CLI and verification helpers for IntentWeave threads."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from intentweave.bundle import export_thread_bundle, import_thread_bundle
from intentweave.errors import ThreadError
from intentweave.fingerprint import history_digest
from intentweave.merge import diff_threads
from intentweave.models import ThreadRecord
from intentweave.service import export_thread_context_blocks
from intentweave.store.sqlite import SQLiteThreadStore


@dataclass
class ThreadVerificationResult:
    """Result of offline tamper-evident SHA-256 chain verification."""

    valid: bool
    thread_id: str
    turns_verified: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "thread_id": self.thread_id,
            "turns_verified": self.turns_verified,
            "errors": list(self.errors),
        }


def verify_thread_records(
    thread_id: str, records: list[ThreadRecord]
) -> ThreadVerificationResult:
    """Verify the SHA-256 history digest chain across all turns of a thread."""
    if not records:
        return ThreadVerificationResult(
            valid=False,
            thread_id=thread_id,
            turns_verified=0,
            errors=[f"Thread '{thread_id}' not found."],
        )

    by_id: dict[str, ThreadRecord] = {rec.response_id: rec for rec in records}
    errors: list[str] = []

    roots = [rec for rec in records if rec.parent_response_id is None]
    if len(roots) != 1:
        errors.append(
            f"Expected exactly 1 root turn (parent_response_id=None), found {len(roots)}."
        )

    for rec in records:
        expected_digest = rec.fingerprint.get("history_digest")
        if not expected_digest:
            errors.append(f"Turn '{rec.response_id}' is missing history_digest in fingerprint.")
        else:
            actual_digest = history_digest(system=rec.system, messages=rec.messages)
            if actual_digest != expected_digest:
                errors.append(
                    f"Turn '{rec.response_id}' history digest mismatch: "
                    f"expected {expected_digest}, got {actual_digest}."
                )

        if rec.parent_response_id is not None:
            parent = by_id.get(rec.parent_response_id)
            if parent is None:
                errors.append(
                    f"Turn '{rec.response_id}' references missing parent "
                    f"'{rec.parent_response_id}'."
                )
            else:
                if rec.system != parent.system:
                    errors.append(
                        f"Turn '{rec.response_id}' system prompt differs from parent "
                        f"'{parent.response_id}'."
                    )
                if rec.messages[: len(parent.messages)] != parent.messages:
                    errors.append(
                        f"Turn '{rec.response_id}' messages do not preserve parent "
                        f"'{parent.response_id}' history prefix."
                    )

    # Check for cycles in parent pointers.
    for rec in records:
        seen: set[str] = set()
        curr: ThreadRecord | None = rec
        while curr is not None:
            if curr.response_id in seen:
                errors.append(f"Cycle detected in parent chain involving '{curr.response_id}'.")
                break
            seen.add(curr.response_id)
            if curr.parent_response_id is None:
                break
            curr = by_id.get(curr.parent_response_id)

    return ThreadVerificationResult(
        valid=len(errors) == 0,
        thread_id=thread_id,
        turns_verified=len(records),
        errors=errors,
    )


def verify_thread_db(db_path: str | Path, thread_id: str) -> ThreadVerificationResult:
    """Open a SQLite thread database offline and verify a thread's SHA-256 chain."""
    path = Path(db_path)
    if not path.exists():
        return ThreadVerificationResult(
            valid=False,
            thread_id=thread_id,
            turns_verified=0,
            errors=[f"Database file not found: {path}"],
        )

    store = SQLiteThreadStore(path)
    try:
        records = store.list_by_thread(thread_id)
        if not records:
            # Allow looking up by a specific response_id to resolve its thread_id.
            single = store.get(thread_id)
            if single is not None:
                records = store.list_by_thread(single.thread_id)
                thread_id = single.thread_id
        return verify_thread_records(thread_id, records)
    finally:
        store.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intentweave",
        description="IntentWeave CLI utilities.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    verify_cmd = sub.add_parser(
        "verify",
        help="Verify tamper-evident SHA-256 history digest chain for a thread offline.",
    )
    verify_cmd.add_argument("--db", required=True, help="Path to SQLiteThreadStore database file.")
    verify_cmd.add_argument("--thread-id", required=True, help="Thread ID (or response ID).")
    verify_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    fork_cmd = sub.add_parser(
        "fork",
        help="Cryptographically fork a thread up to a specific turn.",
    )
    fork_cmd.add_argument("--db", required=True, help="Path to SQLiteThreadStore database file.")
    fork_cmd.add_argument("--thread-id", required=True, help="Source thread ID (or response ID).")
    fork_cmd.add_argument(
        "--up-to-turn",
        type=int,
        default=None,
        help="0-based turn index to fork through (defaults to latest turn).",
    )
    fork_cmd.add_argument(
        "--new-thread-id",
        default=None,
        help="Optional explicit thread_id for the forked child thread.",
    )
    fork_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    export_cmd = sub.add_parser(
        "export-context",
        help="Export thread messages as PromptWeave-compatible context_blocks JSON.",
    )
    export_cmd.add_argument("--db", required=True, help="Path to SQLiteThreadStore database file.")
    export_cmd.add_argument("--thread-id", required=True, help="Thread ID (or response ID).")
    export_cmd.add_argument(
        "--max-turns",
        type=int,
        default=10,
        help="Maximum number of recent messages to export (default: 10).",
    )
    export_cmd.add_argument(
        "--base-priority",
        type=int,
        default=50,
        help="Base priority assigned to the oldest exported message (default: 50).",
    )
    export_cmd.add_argument(
        "--from-checkpoint",
        action="store_true",
        default=False,
        help="Emit latest checkpoint summary followed only by post-checkpoint turns.",
    )
    export_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON output (default format).",
    )

    ckpt_cmd = sub.add_parser(
        "checkpoint",
        help="Create a cryptographic compaction checkpoint for a thread.",
    )
    ckpt_cmd.add_argument("--db", required=True, help="Path to SQLiteThreadStore database file.")
    ckpt_cmd.add_argument("--thread-id", required=True, help="Thread ID (or response ID).")
    ckpt_cmd.add_argument(
        "--summary",
        required=True,
        help="Summary text representing turns covered by this checkpoint.",
    )
    ckpt_cmd.add_argument(
        "--up-to-turn",
        type=int,
        default=None,
        help="0-based turn index covered by the checkpoint (defaults to latest turn).",
    )
    ckpt_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    diff_cmd = sub.add_parser(
        "diff-threads",
        help="Compare two thread branches (common prefix, diverged turns, intent shifts).",
    )
    diff_cmd.add_argument("--db", required=True, help="Path to SQLiteThreadStore database file.")
    diff_cmd.add_argument("--thread-a", required=True, help="First thread ID (or response ID).")
    diff_cmd.add_argument("--thread-b", required=True, help="Second thread ID (or response ID).")
    diff_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    exp_bundle_cmd = sub.add_parser(
        "export-bundle",
        help="Export a verified portable node-snapshot-v1 thread bundle.",
    )
    exp_bundle_cmd.add_argument(
        "--db", required=True, help="Path to SQLiteThreadStore database file."
    )
    exp_bundle_cmd.add_argument(
        "--thread-id", required=True, help="Thread ID (or response ID) to export."
    )
    exp_bundle_cmd.add_argument(
        "--out", required=True, help="Output directory for bundle and snapshot-manifest.json."
    )
    exp_bundle_cmd.add_argument(
        "--node-id", default="local-node", help="Origin node identifier (default: local-node)."
    )
    exp_bundle_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    imp_bundle_cmd = sub.add_parser(
        "import-bundle",
        help="Verify and import a portable node-snapshot-v1 thread bundle into SQLite.",
    )
    imp_bundle_cmd.add_argument(
        "--db", required=True, help="Path to target SQLiteThreadStore database file."
    )
    imp_bundle_cmd.add_argument(
        "--manifest", required=True, help="Path to snapshot-manifest.json."
    )
    imp_bundle_cmd.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "verify":
        result = verify_thread_db(args.db, args.thread_id)
        if args.as_json:
            print(json.dumps(result.to_dict(), indent=2))
        elif result.valid:
            print(f"OK: thread '{result.thread_id}' verified ({result.turns_verified} turn(s)).")
        else:
            print(
                f"INVALID: thread '{result.thread_id}' failed verification "
                f"({len(result.errors)} error(s)):",
                file=sys.stderr,
            )
            for err in result.errors:
                print(f"  - {err}", file=sys.stderr)
        return 0 if result.valid else 1

    if args.command == "fork":
        path = Path(args.db)
        if not path.exists():
            print(f"Error: database file not found: {path}", file=sys.stderr)
            return 1
        store = SQLiteThreadStore(path)
        try:
            summary = store.fork_thread(
                args.thread_id,
                new_thread_id=args.new_thread_id,
                up_to_turn=args.up_to_turn,
            )
        except ThreadError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
        finally:
            store.close()

        if args.as_json:
            print(json.dumps(summary, indent=2))
        else:
            print(
                f"FORKED: '{summary['parent_thread_id']}' (turn {summary['parent_turn']}) -> "
                f"'{summary['thread_id']}' ({summary['turns_copied']} turn(s), "
                f"head={summary['head_response_id']})"
            )
        return 0

    if args.command == "export-context":
        path = Path(args.db)
        if not path.exists():
            print(f"Error: database file not found: {path}", file=sys.stderr)
            return 1
        store = SQLiteThreadStore(path)
        try:
            blocks = export_thread_context_blocks(
                store,
                args.thread_id,
                max_turns=args.max_turns,
                base_priority=args.base_priority,
                from_checkpoint=args.from_checkpoint,
            )
        except ThreadError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
        finally:
            store.close()

        print(json.dumps(blocks, indent=2))
        return 0

    if args.command == "checkpoint":
        path = Path(args.db)
        if not path.exists():
            print(f"Error: database file not found: {path}", file=sys.stderr)
            return 1
        store = SQLiteThreadStore(path)
        try:
            checkpoint = store.create_checkpoint(
                args.thread_id,
                summary_text=args.summary,
                up_to_turn=args.up_to_turn,
            )
        except ThreadError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
        finally:
            store.close()

        if args.as_json:
            print(json.dumps(checkpoint, indent=2))
        else:
            print(
                f"CHECKPOINT: '{checkpoint['checkpoint_id']}' thread='{checkpoint['thread_id']}' "
                f"up_to_turn={checkpoint['up_to_turn']} "
                f"digest={checkpoint['covered_digest'][:16]}..."
            )
        return 0

    if args.command == "diff-threads":
        path = Path(args.db)
        if not path.exists():
            print(f"Error: database file not found: {path}", file=sys.stderr)
            return 1
        store = SQLiteThreadStore(path)
        try:
            diff = diff_threads(store, args.thread_a, args.thread_b)
        except ThreadError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
        finally:
            store.close()

        if args.as_json:
            print(json.dumps(diff, indent=2))
        else:
            print(
                f"DIFF: '{diff['thread_a_id']}' ({diff['thread_a_turns']} turn(s)) vs "
                f"'{diff['thread_b_id']}' ({diff['thread_b_turns']} turn(s)) | "
                f"common_prefix={diff['common_prefix_turns']} "
                f"only_in_a={len(diff['only_in_a'])} only_in_b={len(diff['only_in_b'])} "
                f"intent_shifts={len(diff['intent_shifts'])}"
            )
        return 0

    if args.command == "export-bundle":
        path = Path(args.db)
        if not path.exists():
            print(f"Error: database file not found: {path}", file=sys.stderr)
            return 1
        store = SQLiteThreadStore(path)
        try:
            manifest = export_thread_bundle(
                store,
                args.thread_id,
                args.out,
                node_id=args.node_id,
            )
        except (ThreadError, ValueError, OSError) as exc:
            msg = exc.message if isinstance(exc, ThreadError) else str(exc)
            print(f"Error: {msg}", file=sys.stderr)
            return 1
        finally:
            store.close()

        if args.as_json:
            print(json.dumps(manifest, indent=2))
        else:
            print(
                f"EXPORTED: snapshot_id='{manifest['snapshot_id']}' "
                f"node_id='{manifest['node_id']}' "
                f"checksum={manifest['checksum_sha256'][:16]}..."
            )
        return 0

    if args.command == "import-bundle":
        store = SQLiteThreadStore(args.db)
        try:
            summary = import_thread_bundle(args.manifest, store)
        except (ThreadError, ValueError, OSError) as exc:
            msg = exc.message if isinstance(exc, ThreadError) else str(exc)
            print(f"Error: {msg}", file=sys.stderr)
            return 1
        finally:
            store.close()

        if args.as_json:
            print(json.dumps(summary, indent=2))
        else:
            print(
                f"IMPORTED: thread='{summary['thread_id']}' "
                f"turns={summary['turns_imported']} "
                f"checkpoints={summary['checkpoints_imported']}"
            )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
