FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Writable HOME for Claude Code CLI config
ENV HOME=/root
RUN mkdir -p /root/.claude

# Prevent "nested session" detection
ENV CLAUDECODE=""

# Node.js required for Claude Code CLI
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI and verify
RUN npm install -g @anthropic-ai/claude-code && \
    which claude && claude --version

# Install simmer-sdk from local path
COPY simmer-sdk/ /tmp/simmer-sdk/
RUN pip install --no-cache-dir /tmp/simmer-sdk/ && rm -rf /tmp/simmer-sdk/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/ worker/

CMD ["python", "-m", "worker.main"]
