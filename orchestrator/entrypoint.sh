#!/bin/sh
# Fix ownership of anything under /data not already owned by `worker`, then run uvicorn
# as that non-root user — the SAME uid the worker container uses (1000).
#
# Why this exists: the orchestrator CREATES workspace databases (POST /workspaces ->
# init_db). It used to run as root, so those files were root-owned and the worker —
# which runs as `worker` — could not open them for writing, and every job in a
# workspace created after the worker booted failed with "attempt to write a readonly
# database". A shared uid removes the asymmetry: whatever either service creates in
# /data, the other can write. Colima's bind mount masked this by remapping ownership;
# it reproduces on any real filesystem (a Linux host, or the named orrery-data volume).
#
# `find ! -user worker` rather than a blanket `chown -R` so this stays cheap on a large
# corpus: only mis-owned paths (a fresh bind mount, or a pre-existing root-owned DB) are
# touched, and an already-correct tree costs a stat walk.
find /data \! -user worker -exec chown worker:worker {} + 2>/dev/null || true

# FAIL CLOSED on the REAL invariant — can the `worker` user actually WRITE to /data? —
# not on ownership. Ownership is the wrong test: a bind mount (Colima/virtiofs, and Linux
# hosts where ./data belongs to another uid) reports host uids that root cannot even
# chown, yet still grants the container write access. An ownership check therefore refuses
# a configuration that works — it broke `docker compose up` on the default ./data mount.
# A write probe is precisely what #70 is about ("can the service write its databases"),
# and it is correct on every filesystem: chown-repaired volumes pass, remapped bind mounts
# pass, and a genuinely read-only mount still fails closed.
#
# mktemp with a random suffix, not a fixed marker: an exclusive unique file cannot clobber
# a pre-existing path, and creating a NEW file is what actually tests write access to the
# directory (touch on an existing file only tests that file's mode).
# Sweep first: a SIGKILL in the tiny window between mktemp and rm would leave a probe file
# behind, so clear any from a previous crash (the pattern is ours alone).
rm -f /data/.worker_write_check.* 2>/dev/null || true
if ! su worker -c 'p=$(mktemp /data/.worker_write_check.XXXXXX 2>/dev/null) && rm -f "$p"'; then
    echo "FATAL: the 'worker' user cannot write to /data; starting anyway would recreate" \
         "the readonly-database failure (#70). Fix the mount's permissions and restart." >&2
    exit 1
fi
exec su worker -c "cd /app/orchestrator && uv run uvicorn src.main:app --host 0.0.0.0 --port 8000"
