# ABOUTME: Docker build for the worker (background job processor).
# ABOUTME: Uses uv for dependency management; includes Node.js + Claude CLI for simmer judge board.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install Node.js + Claude CLI (needed by simmer-sdk judge board)
# The bundled CLI in claude-agent-sdk has a broken subprocess transport;
# installing the system CLI lets simmer-sdk's get_cli_path() find a working binary.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Mirror repo layout so ../packages/orrery-relay resolves from pyproject.toml
COPY packages/orrery-relay/ /app/packages/orrery-relay/

WORKDIR /app/worker

# Install dependencies from lockfile
COPY worker/pyproject.toml worker/uv.lock ./
RUN uv sync --frozen --no-cache --no-dev

# Install simmer-sdk into the project venv (internal dep — not the PyPI package, which is unrelated)
RUN uv pip install --no-cache-dir "simmer-sdk @ git+https://github.com/2389-research/simmer-sdk.git"

# Copy application code
COPY worker/src/ src/

# Run as non-root user (Claude CLI refuses --dangerously-skip-permissions as root)
RUN useradd --create-home --shell /bin/bash worker
RUN chown -R worker:worker /app
USER worker

CMD ["uv", "run", "python", "-m", "src.main"]
