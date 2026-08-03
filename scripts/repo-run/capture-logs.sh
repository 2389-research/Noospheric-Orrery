#!/usr/bin/env bash
# ABOUTME: Tee worker+orchestrator container logs to a file for the duration of a run.
# ABOUTME: The worker now emits the relay per-call trace (model/tokens/cache/latency).
#
# Run in its own terminal BEFORE kicking off ingest.py. Ctrl-C to stop.
#   scripts/repo-run/capture-logs.sh [out-file]

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="${1:-$HERE/runs/logs-$(date +%Y%m%d-%H%M%S).log}"
mkdir -p "$(dirname "$OUT")"
cd "$ROOT"

# Prefer the v2 plugin (`docker compose`); fall back to the standalone binary.
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "No Docker Compose found (neither 'docker compose' nor 'docker-compose')." >&2
  exit 1
fi

echo "Streaming worker+orchestrator logs -> $OUT  (via: $DC)  (Ctrl-C to stop)"
$DC logs -f worker orchestrator | tee "$OUT"
