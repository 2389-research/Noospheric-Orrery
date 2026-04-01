FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Prevent "nested session" detection
ENV CLAUDECODE=""

# Skip non-essential traffic in container
ENV DISABLE_AUTOUPDATER=1
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# Install simmer-sdk (pulls claude-agent-sdk which bundles Claude CLI binary)
COPY simmer-sdk/ /tmp/simmer-sdk/
RUN pip install --no-cache-dir /tmp/simmer-sdk/ && rm -rf /tmp/simmer-sdk/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/ worker/

# Non-root user (Claude CLI refuses bypassPermissions as root)
RUN useradd -m -s /bin/bash worker
ENV HOME=/home/worker
RUN mkdir -p /home/worker/.claude && \
    echo '{"hasCompletedOnboarding":true}' > /home/worker/.claude.json && \
    chown -R worker:worker /home/worker /app
USER worker

CMD ["python", "-m", "worker.main"]
