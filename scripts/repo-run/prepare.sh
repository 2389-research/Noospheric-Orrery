#!/usr/bin/env bash
# ABOUTME: Fetch + export each configured repo's origin/main into ./data/repos/<name>
# ABOUTME: so the Orrery containers (mount ./data:/data) can ingest /data/repos/<name>.
#
# Non-destructive: uses `git fetch` + `git archive origin/main` — it does NOT check out
# or modify your working branch, so repos on feature branches stay exactly as they are.
#
# Usage:  scripts/repo-run/prepare.sh [repos.txt]
# Run from the repo root (where ./data lives).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# Prefer a gitignored local config; fall back to the committed template.
if [ -n "${1:-}" ]; then REPOS_FILE="$1"
elif [ -f "$HERE/repos.local.txt" ]; then REPOS_FILE="$HERE/repos.local.txt"
else REPOS_FILE="$HERE/repos.txt"; fi
DEST_ROOT="$ROOT/data/repos"
MANIFEST="$DEST_ROOT/MANIFEST.txt"

cd "$ROOT"
mkdir -p "$DEST_ROOT"
: > "$MANIFEST"
echo "# prepared $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$MANIFEST"
echo "# name  ref  sha  files" >> "$MANIFEST"

while read -r name path _rest; do
  case "$name" in ''|\#*) continue ;; esac
  # Name is used in destructive paths (rm -rf "$DEST_ROOT/$name") — require a
  # single safe path segment so a value like "../.." can't escape data/repos.
  case "$name" in
    .|..|*[!A-Za-z0-9._-]*)
      echo "SKIP  $name — unsafe repo name (must be a single path segment)" >&2
      echo "$name  UNSAFE  -  -" >> "$MANIFEST"
      continue ;;
  esac
  if [ ! -d "$path" ]; then
    echo "SKIP  $name — path does not exist: $path" >&2
    echo "$name  MISSING  -  -" >> "$MANIFEST"
    continue
  fi

  # Plain dir (not its own git repo, e.g. a subdir of this repo) — copy as-is.
  if [ ! -d "$path/.git" ]; then
    echo ">> $name: plain-copy (not a git repo) ..."
    dest="$DEST_ROOT/$name"; rm -rf "$dest"; mkdir -p "$dest"
    rsync -a --exclude '.git' --exclude '__pycache__' --exclude 'node_modules' \
          --exclude 'target' --exclude '.venv' --exclude 'dist' --exclude '.pytest_cache' \
          "$path"/ "$dest"/
    files="$(find "$dest" -type f | wc -l | tr -d ' ')"
    echo "   $name (copied) -> data/repos/$name  ($files files)"
    echo "$name  COPY  -  $files" >> "$MANIFEST"
    continue
  fi

  echo ">> $name: fetching origin ..."
  # Skip on fetch failure rather than exporting a stale cached origin/main — the
  # whole point is an up-to-date, repeatable snapshot.
  if ! git -C "$path" fetch --quiet origin; then
    echo "SKIP  $name — git fetch failed (refusing to export a stale snapshot)" >&2
    echo "$name  FETCH-FAIL  -  -" >> "$MANIFEST"
    continue
  fi

  # Prefer origin/main, fall back to origin/master.
  ref=""
  for cand in origin/main origin/master; do
    if git -C "$path" rev-parse --verify --quiet "$cand" >/dev/null; then ref="$cand"; break; fi
  done
  if [ -z "$ref" ]; then
    echo "SKIP  $name — no origin/main or origin/master" >&2
    echo "$name  NO-MAIN  -  -" >> "$MANIFEST"
    continue
  fi

  sha="$(git -C "$path" rev-parse --short "$ref")"
  dest="$DEST_ROOT/$name"
  rm -rf "$dest"; mkdir -p "$dest"
  # Export tracked files at the tip of main (excludes .git and untracked build junk).
  git -C "$path" archive --format=tar "$ref" | tar -x -C "$dest"
  files="$(find "$dest" -type f | wc -l | tr -d ' ')"

  echo "   $name @ $ref ($sha) -> data/repos/$name  ($files files)"
  echo "$name  $ref  $sha  $files" >> "$MANIFEST"
done < "$REPOS_FILE"

echo
echo "Done. Exported repos:"
cat "$MANIFEST"
echo
echo "Next: (re)build & start the stack, then run the ingest driver:"
echo "  docker compose up --build -d"
echo "  python scripts/repo-run/ingest.py"
