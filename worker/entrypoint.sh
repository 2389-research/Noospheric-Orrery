#!/bin/sh
# Fix ownership of anything under /data not already owned by `worker`, then run as that
# non-root user. `find ! -user worker` rather than a blanket `chown -R` so it stays
# cheap on a large corpus — only mis-owned paths are touched. Mirrors
# orchestrator/entrypoint.sh; both drop to the same uid so either can write what the
# other created.
find /data \! -user worker -exec chown worker:worker {} + 2>/dev/null || true

# FAIL CLOSED on WRITABILITY, not ownership — same as orchestrator/entrypoint.sh, and for
# the same reason: a bind mount reports host uids that root cannot chown yet still lets the
# container write, so an ownership check refuses a working configuration. Probe an actual
# write as the worker user; a genuinely read-only mount still fails closed.
#
# mktemp with a random suffix, not a fixed marker: an exclusive unique file cannot
# clobber a pre-existing path, and creating a NEW file is what actually tests write
# access to the directory (touch on an existing file only tests that file's mode).
if ! su worker -c 'p=$(mktemp /data/.worker_write_check.XXXXXX 2>/dev/null) && rm -f "$p"'; then
    echo "FATAL: the 'worker' user cannot write to /data; starting anyway would recreate" \
         "the readonly-database failure (#70). Fix the mount's permissions and restart." >&2
    exit 1
fi
exec su worker -c "cd /app/worker && uv run python -m src.main"
