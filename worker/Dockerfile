# ABOUTME: Docker build for the worker (background job processor).
# ABOUTME: Uses uv for dependency management. Simmer uses direct API agent loop (no CLI subprocess).

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install git (for simmer-sdk GitHub install)
RUN apt-get update && apt-get install -y --no-install-recommends git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Mirror repo layout so the ../packages/* path sources resolve from pyproject.toml
COPY packages/orrery-relay/ /app/packages/orrery-relay/
COPY packages/orrery-codesum/ /app/packages/orrery-codesum/

WORKDIR /app/worker

# Install dependencies from lockfile (deps only — project not yet copied)
COPY worker/pyproject.toml worker/uv.lock ./
RUN uv sync --frozen --no-cache --no-dev --no-install-project

# Copy application code, then install the project itself
COPY worker/src/ src/
RUN uv sync --frozen --no-cache --no-dev

# Bundle the canonical taxonomy (authored in orchestrator/specs) so the worker
# classifier reads the SAME source as the orchestrator — one authored file.
COPY orchestrator/specs/taxonomy.json /app/worker/taxonomy.json

# Install simmer-sdk AFTER final sync (not in lockfile, so must come after).
# The [local] extra pulls in `openai`, required by simmer-sdk's Ollama agent
# loop (local_agent.py). Without it, every board judge fails with
# "No module named 'openai'" when ANTHROPIC_BACKEND=ollama.
RUN uv pip install --no-cache-dir "simmer-sdk[local] @ git+https://github.com/2389-research/simmer-sdk.git@main"

# Non-root user
RUN useradd -m -s /bin/bash worker
RUN mkdir -p /data && chown -R worker:worker /app /data

COPY worker/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
