#!/usr/bin/env python3
# ABOUTME: Package one workspace's graph into a portable, self-describing archive.
# ABOUTME: Base tables only — derived data is rebuilt by the importer's first open.
"""Export a noosphere so someone else can open it.

A noosphere is exactly two things: a SQLite file and one row in
`data/workspaces/registry.json`. Everything else under `data/` is either derivable or
irrelevant to the graph — document text lives in the DB, so the upload copies are not
needed.

Three things make an export different from `cp`, and each is a real failure rather than
tidiness:

  * The database is WAL-mode. A plain copy without its `-wal` sidecar can silently drop
    the most recent commits, so this uses `VACUUM INTO`, which checkpoints and compacts
    in one step.
  * `layout_model.model_blob` is a PICKLE of a UMAP reducer. It is not on the read path
    (positions are stored in `domain_layout`), so it is dropped: it only unpickles under
    compatible library versions, and re-fitting is cheap next to shipping a landmine.
  * `graph_snapshot` holds a cached payload for one contract version. It is emptied and
    marked dirty, so the importer builds its own rather than serving a stale one.

Usage:
    python3 scripts/export_noosphere.py <workspace-id> [--out DIR] [--data DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# A workspace id becomes a directory name. Keep it to a single, boring path component.
# This matters most on the IMPORT side, where the id can come from the archive's own
# manifest — and an archive is by definition something someone else built — so
# `../../..` must not be spellable. The character class is the whole guard: with no
# separator and no leading dot, traversal is unrepresentable. A resolved-path
# containment check was considered and rejected, because it also refuses a legitimately
# symlinked workspace directory, which is a real setup for a corpus too big for the
# main disk.
#
# Duplicated verbatim in import_noosphere.py: that script ships standalone inside the
# archive and cannot import from here.
_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _workspace_dir(data_dir: Path, workspace: str) -> Path:
    if not _WORKSPACE_ID_RE.match(workspace or ""):
        sys.exit(f"invalid workspace id {workspace!r}: expected a single path component "
                 "of letters, digits, '.', '-' or '_'")
    return data_dir / "workspaces" / workspace


def _counts(conn: sqlite3.Connection) -> dict:
    """Row counts for the tables a recipient will actually look for."""
    out: dict = {}
    for table in ("documents", "entities", "relationships", "domains",
                  "collections", "collection_edges", "entity_embeddings"):
        try:
            out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            out[table] = None      # table absent on an older schema — reported, not fatal
    return out


def _source_path_prefixes(conn: sqlite3.Connection, limit: int = 8) -> list[str]:
    """Distinct leading directories of `documents.source_path`.

    Recorded because these are absolute, container-relative paths that will NOT resolve
    on another machine. The graph works without them; only the drill-down from a node to
    the real file breaks. Listing them tells the recipient exactly what to stage if they
    want that, instead of leaving them to discover a dead link.
    """
    rows = conn.execute(
        "SELECT DISTINCT source_path FROM documents "
        "WHERE source_path IS NOT NULL AND source_path <> '' LIMIT 2000").fetchall()
    prefixes = set()
    for (path,) in rows:
        parts = str(path).split("/")
        prefixes.add("/".join(parts[:3]) if len(parts) > 3 else str(path))
    return sorted(prefixes)[:limit]


def export(workspace: str, data_dir: Path, out_dir: Path) -> Path:
    src = _workspace_dir(data_dir, workspace) / "orrery.db"
    if not src.is_file():
        sys.exit(f"no database at {src}")

    registry_path = data_dir / "workspaces" / "registry.json"
    entry = None
    if registry_path.is_file():
        try:
            loaded = json.loads(registry_path.read_text())
            # A registry that is not a list of objects is corrupt, not fatal: iterating
            # a dict yields str keys, and `.get` on those raises rather than reporting.
            if isinstance(loaded, list):
                entry = next((w for w in loaded
                              if isinstance(w, dict) and w.get("id") == workspace), None)
        except (OSError, ValueError):
            entry = None
    if entry is None:
        # Not fatal: the id is enough to register on the far side, and a missing registry
        # should not block an export whose real payload is the database.
        print(f"! no registry entry for {workspace!r}; using the id as the name")
        entry = {"id": workspace, "name": workspace, "description": "",
                 "status": "active"}

    out_dir.mkdir(parents=True, exist_ok=True)
    staged = out_dir / "orrery.db"
    # `--out data/workspaces/<id>` makes `staged` the live database, and the unlink
    # below would then delete the corpus this is supposed to be exporting — before
    # VACUUM INTO ever runs, so there is nothing left to recover from.
    if staged.resolve() == src.resolve():
        sys.exit(f"--out is the workspace directory itself ({out_dir}); that would "
                 "delete the database being exported")
    if staged.exists():
        staged.unlink()

    # VACUUM INTO, never a file copy: checkpoints the WAL and compacts in one step, and
    # reads a consistent snapshot even while the services are running.
    print(f"exporting {src} ({src.stat().st_size / 1e6:.0f} MB) ...")
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as conn:
        conn.execute("VACUUM INTO ?", (str(staged),))

    with sqlite3.connect(staged) as conn:
        counts = _counts(conn)
        prefixes = _source_path_prefixes(conn)
        # Derived, disposable, and actively harmful to ship — see the module docstring.
        conn.execute("DELETE FROM layout_model")
        conn.execute("UPDATE graph_snapshot SET payload = NULL, dirty = 1")
        conn.commit()
        conn.execute("VACUUM")

    manifest = {
        "workspace": {k: entry.get(k) for k in ("id", "name", "description")},
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_from_commit": _git_commit(),
        "counts": counts,
        "source_path_prefixes": prefixes,
        "notes": [
            "Open with the exporting commit or NEWER — migrations are forward-only.",
            "Deploy the code BEFORE placing the database; a running orchestrator "
            "opens new workspaces within ~20s and a pre-rename corpus must be "
            "migrated on its first open.",
            "The first GET /graph builds the snapshot and can take several minutes "
            "on a large corpus; later calls are cached.",
            "source_path values are absolute container paths and will not resolve "
            "here. The graph is unaffected; only drill-down to the real file is.",
        ],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    shutil.copy(Path(__file__).parent / "NOOSPHERE.md", out_dir / "NOOSPHERE.md")
    shutil.copy(Path(__file__).parent / "import_noosphere.py",
                out_dir / "import_noosphere.py")

    print(f"\nwrote {out_dir}/")
    print(f"  orrery.db          {staged.stat().st_size / 1e6:.0f} MB")
    print(f"  manifest.json      {json.dumps(counts)}")
    print(f"  NOOSPHERE.md       instructions for the recipient (and their agent)")
    print(f"  import_noosphere.py")
    return out_dir


def _git_commit() -> str | None:
    """The commit this was exported from — the floor a recipient should check out."""
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                           text=True, timeout=10, cwd=Path(__file__).parent.parent)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Package a noosphere for another machine.")
    ap.add_argument("workspace", help="workspace id, e.g. swe-org")
    ap.add_argument("--data", default="data", help="data dir (default: ./data)")
    ap.add_argument("--out", default=None, help="output dir (default: ./<workspace>-noosphere)")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else Path(f"{a.workspace}-noosphere")
    export(a.workspace, Path(a.data), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
