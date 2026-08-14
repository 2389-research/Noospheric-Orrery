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
if ! su worker -c 'touch /data/.worker_write_check 2>/dev/null && rm -f /data/.worker_write_check'; then
    echo "FATAL: the 'worker' user cannot write to /data; starting anyway would recreate" \
         "the readonly-database failure (#70). Fix the mount's permissions and restart." >&2
    exit 1
fi
exec su worker -c "cd /app/worker && uv run python -m src.main"
