FROM python:3.11-slim
WORKDIR /app

# Prevent "nested session" detection
ENV CLAUDECODE=""
ENV DISABLE_AUTOUPDATER=1
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# Install Node.js + Claude Code CLI (for simmer-sdk judge board)
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && \
    npm install -g @anthropic-ai/claude-code && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install orrery-relay (shared LLM client SDK)
COPY packages/orrery-relay/ /tmp/orrery-relay/
RUN pip install --no-cache-dir /tmp/orrery-relay/ && rm -rf /tmp/orrery-relay/

# Install simmer-sdk (internal dependency)
COPY worker/simmer-sdk/ /tmp/simmer-sdk/
RUN pip install --no-cache-dir /tmp/simmer-sdk/ && rm -rf /tmp/simmer-sdk/

COPY worker/pyproject.toml .
RUN pip install --no-cache-dir .
COPY worker/src/ src/

# Non-root user (Claude CLI refuses --dangerously-skip-permissions as root)
RUN useradd -m -s /bin/bash worker
ENV HOME=/home/worker
RUN mkdir -p /home/worker/.claude /data && \
    echo '{"hasCompletedOnboarding":true}' > /home/worker/.claude.json && \
    chown -R worker:worker /home/worker /app /data
COPY worker/entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "src.main"]
