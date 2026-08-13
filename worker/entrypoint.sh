#!/bin/sh
# Fix ownership of anything under /data not already owned by `worker`, then run as that
# non-root user. `find ! -user worker` rather than a blanket `chown -R` so it stays
# cheap on a large corpus — only mis-owned paths are touched. Mirrors
# orchestrator/entrypoint.sh; both drop to the same uid so either can write what the
# other created.
find /data \! -user worker -exec chown worker:worker {} + 2>/dev/null || true
exec su worker -c "cd /app/worker && uv run python -m src.main"
