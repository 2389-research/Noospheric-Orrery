#!/usr/bin/env python3
# ABOUTME: Install an exported noosphere into a local checkout's data dir.
# ABOUTME: Refuses to run while the services are up — that ordering is load-bearing.
"""Install a noosphere archive.

Ordering matters, and this is the part a human (or an agent) gets wrong: the
orchestrator's background snapshot loop opens every registered workspace within ~20
seconds. If it reaches a pre-rename corpus while running OLD code, it creates the empty
collection tables beside the populated legacy ones — and the migration then correctly
REFUSES the database, because both names exist and no safe automatic merge is possible.

So: code first, services down, then place the file. This script enforces the "services
down" half rather than trusting a README.

Usage:
    python3 import_noosphere.py [--id ID] [--data DIR] [--force]

`--force` overwrites an existing workspace database. It does NOT bypass the
services-down check, which is unconditional — see the comment on it below.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The id becomes a directory name, and it defaults to one read out of the ARCHIVE's
# manifest — which is something someone else built. Restricting it to a single path
# component makes `../../..` unrepresentable. See the matching note in
# export_noosphere.py for why this is a character class and not a resolved-path check;
# the helper is duplicated because this script ships standalone inside the archive.
_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _services_are_up(port: int = 8100) -> bool:
    try:
        urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2).read(16)
        return True
    except (urllib.error.URLError, OSError):
        return False


def _assert_readable_sqlite(path: Path) -> None:
    """Fail before anything is written, not after.

    `is_file()` accepts any bytes at all. Copying those over an existing workspace and
    appending a registry entry, only to discover at the very end that the file is not a
    database, leaves the target strictly worse than it started.
    """
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.DatabaseError as exc:
        sys.exit(f"{path} is not a readable SQLite database ({exc})")


def _load_manifest(path: Path) -> dict:
    """A manifest is optional, but a malformed one must not crash mid-install."""
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        sys.exit(f"{path} is not readable JSON ({exc})")
    if not isinstance(loaded, dict):
        sys.exit(f"{path} should contain a JSON object, got {type(loaded).__name__}")
    return loaded


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Install an exported noosphere.")
    ap.add_argument("--data", default="data", help="target data dir (default: ./data)")
    ap.add_argument("--id", default=None, help="workspace id (default: from manifest)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing workspace database")
    ap.add_argument("--skip-service-check", action="store_true",
                    help="ONLY when the :8100 probe is a false positive (something "
                         "unrelated is on that port). Never to install into a live stack.")
    a = ap.parse_args(argv)

    db_src = HERE / "orrery.db"
    if not db_src.is_file():
        sys.exit(f"no orrery.db beside this script ({HERE})")
    # Everything below this line writes. Validate the archive first: a half-installed
    # workspace with a registry entry pointing at garbage is worse than a failed run.
    _assert_readable_sqlite(db_src)

    manifest = _load_manifest(HERE / "manifest.json")
    ws = manifest.get("workspace")
    if not isinstance(ws, dict):
        ws = {}
    ws_id = a.id or ws.get("id") or "imported"
    if not isinstance(ws_id, str) or not _WORKSPACE_ID_RE.match(ws_id):
        sys.exit(f"invalid workspace id {ws_id!r}: expected a single path component of "
                 "letters, digits, '.', '-' or '_'. Override it with --id NAME.")
    ws_name = ws.get("name") or ws_id

    # Unconditional, and deliberately not covered by --force. Being on current code —
    # the reason this stop exists — does nothing about the second hazard: replacing the
    # main database file and deleting its -wal/-shm while a live process holds them open
    # corrupts the workspace. Stopping the stack is one command; there is no case where
    # writing underneath a running orchestrator is the right move.
    if _services_are_up() and not a.skip_service_check:
        sys.exit(
            "The orchestrator is answering on :8100. Stop the stack before installing:\n"
            "    docker-compose stop orchestrator worker\n\n"
            "This is not caution for its own sake, and there are two reasons:\n"
            "  * A running orchestrator opens every registered workspace within ~20s,\n"
            "    and if it reaches this database while the checkout is on older code it\n"
            "    creates empty collection tables beside the populated legacy ones —\n"
            "    after which the migration REFUSES the file, because both names exist\n"
            "    and merging them automatically is not safe.\n"
            "  * Overwriting the database and its -wal/-shm sidecars underneath an open\n"
            "    handle corrupts the workspace.\n\n"
            "--skip-service-check exists only for a false positive on :8100.")

    data = Path(a.data)
    target_dir = data / "workspaces" / ws_id
    target = target_dir / "orrery.db"
    if target.exists() and not a.force:
        sys.exit(f"{target} already exists — pass --force to overwrite, or use --id NAME")
    target_dir.mkdir(parents=True, exist_ok=True)

    print(f"installing {db_src.name} -> {target}")
    shutil.copy(db_src, target)
    # Any stale sidecar belongs to the OLD file and would be read against the new one.
    for suffix in ("-wal", "-shm"):
        stale = Path(str(target) + suffix)
        if stale.exists():
            stale.unlink()

    registry_path = data / "workspaces" / "registry.json"
    registry = []
    if registry_path.is_file():
        try:
            loaded = json.loads(registry_path.read_text())
        except ValueError:
            loaded = None
        # Anything but a list of objects is unusable: iterating a dict yields str keys,
        # and `.get` on those raises instead of reporting.
        if isinstance(loaded, list):
            registry = [w for w in loaded if isinstance(w, dict)]
        else:
            print("! registry.json is unreadable; writing a fresh one")
    if not any(w.get("id") == ws_id for w in registry):
        registry.append({
            "id": ws_id, "name": ws_name,
            "description": ws.get("description") or "imported noosphere",
            "status": "active",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        })
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic, matching how the orchestrator writes it: a torn registry loses every
        # workspace, not just this one.
        tmp = registry_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(registry, indent=2))
        os.replace(tmp, registry_path)
        print(f"registered workspace {ws_id!r} ({ws_name})")
    else:
        print(f"workspace {ws_id!r} already in the registry")

    with sqlite3.connect(target) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    legacy = {"repos", "document_repos", "repo_edges"} & tables
    if legacy:
        print(f"\nnote: pre-rename tables present ({', '.join(sorted(legacy))}).")
        print("      They migrate automatically on first open — which is exactly why the")
        print("      code must already be current. Verify afterwards with:")
        print("        sqlite3 %s 'SELECT COUNT(*) FROM collections;'" % target)

    counts = manifest.get("counts")
    if isinstance(counts, dict) and counts:
        print("\nexpected after first open:")
        for k, v in counts.items():
            if v:
                print(f"  {k:22s} {v}")
    print("\nnext:")
    print("  1. docker-compose up -d          # or restart the stack")
    print("  2. open the workspace in the UI")
    print("  3. the FIRST /graph builds the snapshot and may take several minutes")
    print("     on a large corpus. That is a build, not a hang; later calls are cached.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
