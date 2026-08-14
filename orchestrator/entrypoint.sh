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

# FAIL CLOSED. The repair above is best-effort (its errors are suppressed so transient
# find noise doesn't abort startup), so verify the invariant it exists to guarantee: if
# anything under /data is STILL not owned by worker, do not start the service as worker
# on top of files it cannot write — that is exactly the readonly-database failure (#70)
# this entrypoint prevents, and silently starting into it is worse than not starting.
leftover=$(find /data \! -user worker -print -quit 2>/dev/null)
if [ -n "$leftover" ]; then
    echo "FATAL: /data still holds files not owned by 'worker' (e.g. ${leftover}); the" \
         "ownership repair did not complete, and starting as 'worker' would recreate the" \
         "readonly-database failure (#70). Fix the mount's ownership and restart." >&2
    exit 1
fi
exec su worker -c "cd /app/orchestrator && uv run uvicorn src.main:app --host 0.0.0.0 --port 8000"
