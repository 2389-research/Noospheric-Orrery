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
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _services_are_up(port: int = 8100) -> bool:
    try:
        urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2).read(16)
        return True
    except (urllib.error.URLError, OSError):
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Install an exported noosphere.")
    ap.add_argument("--data", default="data", help="target data dir (default: ./data)")
    ap.add_argument("--id", default=None, help="workspace id (default: from manifest)")
    ap.add_argument("--force", action="store_true",
                    help="install even though the orchestrator is reachable")
    a = ap.parse_args(argv)

    db_src = HERE / "orrery.db"
    manifest_path = HERE / "manifest.json"
    if not db_src.is_file():
        sys.exit(f"no orrery.db beside this script ({HERE})")
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    ws = manifest.get("workspace", {})
    ws_id = a.id or ws.get("id") or "imported"
    ws_name = ws.get("name") or ws_id

    if _services_are_up() and not a.force:
        sys.exit(
            "The orchestrator is answering on :8100. Stop the stack before installing:\n"
            "    docker-compose stop orchestrator worker\n\n"
            "This is not caution for its own sake. A running orchestrator opens every\n"
            "registered workspace within ~20s, and if it reaches this database while the\n"
            "checkout is on older code it creates empty collection tables beside the\n"
            "populated legacy ones — after which the migration REFUSES the file, because\n"
            "both names exist and merging them automatically is not safe.\n\n"
            "Re-run with --force only if you are certain the code is current.")

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
            registry = json.loads(registry_path.read_text())
        except ValueError:
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

    counts = manifest.get("counts") or {}
    if counts:
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
