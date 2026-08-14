#!/bin/sh
# Fix ownership of anything under /data not already owned by `worker`, then run as that
# non-root user. `find ! -user worker` rather than a blanket `chown -R` so it stays
# cheap on a large corpus — only mis-owned paths are touched. Mirrors
# orchestrator/entrypoint.sh; both drop to the same uid so either can write what the
# other created.
find /data \! -user worker -exec chown worker:worker {} + 2>/dev/null || true

# FAIL CLOSED — same as orchestrator/entrypoint.sh. The repair is best-effort, so verify
# it worked: if any file under /data is still not owned by worker, refuse to start rather
# than run as worker on top of files it cannot write (the readonly-database failure #70).
leftover=$(find /data \! -user worker -print -quit 2>/dev/null)
if [ -n "$leftover" ]; then
    echo "FATAL: /data still holds files not owned by 'worker' (e.g. ${leftover}); the" \
         "ownership repair did not complete. Fix the mount's ownership and restart." >&2
    exit 1
fi
exec su worker -c "cd /app/worker && uv run python -m src.main"
