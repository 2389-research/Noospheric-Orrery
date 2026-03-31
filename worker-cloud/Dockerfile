FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Node.js required for Claude Code CLI (used by simmer-sdk via claude-agent-sdk)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI (simmer-sdk calls this as subprocess)
RUN npm install -g @anthropic-ai/claude-code

# Install simmer-sdk from local path (same as worker/Dockerfile)
COPY simmer-sdk/ /tmp/simmer-sdk/
RUN pip install --no-cache-dir /tmp/simmer-sdk/ && rm -rf /tmp/simmer-sdk/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/ worker/

# Cloud Run Job: runs once and exits
CMD ["python", "-m", "worker.main"]
