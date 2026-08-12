#!/usr/bin/env python3
# ABOUTME: Backfill git provenance (remote_url + commit_sha) onto collections ingested
# ABOUTME: before it was captured, so /documents/{id} returns a resolvable git_ref.
"""
Populate `collections.remote_url` / `collections.commit_sha` for git repos that were
ingested without provenance. `ingest_repo` records these automatically now, but two
populations lack them:

  * repos ingested before the git-ref feature existed, and
  * EVERY repo ingested in Docker before PR #67 — git refused the bind-mounted
    checkout as "dubious ownership", and `_git_coordinates` is best-effort, so it
    silently returned (None, None) with nothing logged.

READ THIS BEFORE USING IT. This pins each repo's CURRENT default-branch HEAD. The
ingest-time SHA was never recorded for these rows, so the backfilled commit is NOT
necessarily the code the stored summaries describe. That matters here more than it
would elsewhere: the whole point of a ref is "fetch the exact version this summary
was written from", and a plausible-but-wrong SHA is the failure mode the ref exists
to avoid. If a repo has moved on since ingestion, the honest fix is to re-ingest it,
not to backfill it. Use this when an approximate ref beats no ref, and know which
one you are getting.

NON-DESTRUCTIVE: only rows still MISSING provenance are touched, so a repo with a
real ingest-time commit_sha is never overwritten. Repos that don't resolve (not found
under the org, or a transient `gh` failure) are skipped — never nulled.

Scoped to `kind = 'git_repo'`. Tracker-run collections are named for the run
(`run1`, `R6-brief`), which is not a GitHub repo — resolving those against the org
would at best 404 and at worst match an unrelated repository and write a ref that
points somewhere real and wrong.

Because the DB is often owned by a container user while `gh` is only authenticated on
the host, resolve and apply can be split:

  # A) single machine (gh + a writable DB here):
  scripts/backfill_git_refs.py --db data/workspaces/default/orrery.db --apply

  # B) split — resolve on the host, apply inside the container:
  scripts/backfill_git_refs.py --db data/workspaces/default/orrery.db --out map.json
  #   (copy map.json to where the container sees it, then:)
  scripts/backfill_git_refs.py --db /data/workspaces/default/orrery.db --apply-map map.json

  # C) dry run (default): print the resolved mapping, touch nothing.
  scripts/backfill_git_refs.py --db data/workspaces/default/orrery.db
"""
import argparse
import json
import sqlite3
import subprocess
import sys


def _gh(*args: str) -> str | None:
    """Run `gh api <args>` (scalar --jq output expected) and return trimmed stdout, or
    None on ANY failure — 404, jq error, or a transient error. Callers treat None as
    "skip", never as "write null"."""
    try:
        r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.strip()
    # returncode!=0 covers 404/jq-failure; a leading '{' is an error object leaking
    # through --jq. Either way it's not a usable scalar.
    if r.returncode != 0 or not out or out.startswith("{"):
        return None
    return out


def resolve(db_path: str, org: str) -> dict:
    """{collection_path: {name, remote, sha}} for git repos missing provenance.

    Keyed on `path`, not `name`: `collections.path` is the UNIQUE key and `name` is
    not, so an update keyed on name could touch more than one row. The GitHub lookup
    still uses the name, which is what the repo is actually called.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    # BOTH null, not either. `_git_coordinates` is all-or-nothing (see
    # worker/src/jobs/ingest_repo.py), so a half-filled pair should not exist — but
    # selecting on "either is null" and then writing BOTH columns would replace a
    # captured ingest-time SHA with the current default-branch HEAD, destroying the
    # one piece of real provenance that row had. That is the exact opposite of what
    # this script promises.
    rows = conn.execute(
        "SELECT path, name FROM collections "
        "WHERE kind = 'git_repo' AND name IS NOT NULL "
        "AND remote_url IS NULL AND commit_sha IS NULL").fetchall()
    # Report half-pairs rather than silently passing over them: one means something
    # wrote provenance outside the all-or-nothing path, which deserves a human look.
    partial = conn.execute(
        "SELECT path FROM collections WHERE kind = 'git_repo' "
        "AND ((remote_url IS NULL) != (commit_sha IS NULL))").fetchall()
    conn.close()
    for row in partial:
        print(f"  {row[0]}: only half a provenance pair -> left alone, repair by hand",
              file=sys.stderr)
    mapping: dict = {}
    for path, name in rows:
        # full_name + default_branch in one call (scalar, '|'-joined).
        info = _gh(f"repos/{org}/{name}", "--jq", '.full_name + "|" + .default_branch')
        if not info or "|" not in info:
            print(f"  {name}: not found under {org} / lookup failed -> skipped", file=sys.stderr)
            continue
        full, branch = info.split("|", 1)
        sha = _gh(f"repos/{org}/{name}/commits/{branch}", "--jq", ".sha") if branch else None
        if not full or not sha:
            print(f"  {name}: incomplete provenance -> skipped", file=sys.stderr)
            continue
        mapping[path] = {"name": name, "remote": f"github.com/{full}", "sha": sha}
        print(f"  {name}: {full}@{branch} {sha[:12]}  (current HEAD, not ingest-time)",
              file=sys.stderr)
    return mapping


def apply(db_path: str, mapping: dict) -> int:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=30000")
    changed = 0
    for path, v in mapping.items():
        remote, sha, name = v.get("remote"), v.get("sha"), v.get("name")
        if not remote or not sha or not name:
            print(f"  {path}: incomplete mapping entry -> skipped", file=sys.stderr)
            continue
        # `name` is part of the predicate, not just the payload. In split mode the
        # map is resolved on one machine and applied on another, possibly much later,
        # so it can be stale: a collection deleted and re-created at the same `path`
        # would otherwise be handed provenance belonging to a DIFFERENT repository —
        # a ref that resolves perfectly and points at the wrong code, which is the
        # failure this whole feature is built to avoid.
        #
        # Both columns must still be NULL: never overwrite captured provenance, and
        # never touch a tracker run.
        cur = conn.execute(
            "UPDATE collections SET remote_url=?, commit_sha=? "
            "WHERE path=? AND name=? AND kind='git_repo' "
            "AND remote_url IS NULL AND commit_sha IS NULL",
            (remote, sha, path, name))
        if cur.rowcount == 0:
            print(f"  {path}: no matching row still missing provenance "
                  f"(renamed, refilled, or removed since resolve) -> skipped",
                  file=sys.stderr)
        changed += cur.rowcount
    conn.commit()
    conn.close()
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Backfill git provenance onto collections (non-destructive, "
                    "pins CURRENT default-branch HEAD — see the module docstring).")
    ap.add_argument("--db", required=True, help="path to the orrery SQLite DB")
    ap.add_argument("--org", default="2389-research", help="GitHub org (default: 2389-research)")
    ap.add_argument("--out", help="write the resolved mapping to this JSON file")
    ap.add_argument("--apply", action="store_true", help="resolve AND write to the DB")
    ap.add_argument("--apply-map", help="apply a previously-resolved mapping JSON (skips gh)")
    args = ap.parse_args()

    if args.apply_map:
        with open(args.apply_map) as f:
            mapping = json.load(f)
        print(f"applied to {apply(args.db, mapping)} collection row(s)")
        return

    print(f"resolving git repos missing provenance against github.com/{args.org} ...",
          file=sys.stderr)
    mapping = resolve(args.db, args.org)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(mapping, f, indent=1)
        print(f"wrote mapping ({len(mapping)} repos) -> {args.out}")
    if args.apply:
        n = apply(args.db, mapping)
        print(f"applied to {n} collection row(s) — each pinned to CURRENT "
              f"default-branch HEAD, not the ingested commit")
    if not args.out and not args.apply:
        print(json.dumps(mapping, indent=1))  # dry run


if __name__ == "__main__":
    main()
