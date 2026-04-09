# ABOUTME: Docker build for the worker (background job processor).
# ABOUTME: Uses uv for dependency management; includes Node.js + Claude CLI for simmer judge board.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Prevent "nested session" detection
ENV CLAUDECODE=""
ENV DISABLE_AUTOUPDATER=1
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# Install git (for simmer-sdk GitHub install), Node.js + Claude Code CLI (for simmer judge board)
RUN apt-get update && apt-get install -y --no-install-recommends git nodejs npm && \
    npm install -g @anthropic-ai/claude-code && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Mirror repo layout so ../packages/orrery-relay resolves from pyproject.toml
COPY packages/orrery-relay/ /app/packages/orrery-relay/

WORKDIR /app/worker

# Install dependencies from lockfile
COPY worker/pyproject.toml worker/uv.lock ./
RUN uv sync --frozen --no-cache --no-dev

# Install simmer-sdk v0.3.0 from GitHub (internal dep — not the PyPI package, which is unrelated)
RUN uv pip install --no-cache-dir "simmer-sdk @ git+https://github.com/2389-research/simmer-sdk.git@v0.3.0"

# Copy application code
COPY worker/src/ src/

# Non-root user (Claude CLI refuses --dangerously-skip-permissions as root)
RUN useradd -m -s /bin/bash worker
ENV HOME=/home/worker
RUN mkdir -p /home/worker/.claude /data && \
    echo '{"hasCompletedOnboarding":true}' > /home/worker/.claude.json && \
    chown -R worker:worker /home/worker /app /data
USER worker

CMD ["uv", "run", "python", "-m", "src.main"]
