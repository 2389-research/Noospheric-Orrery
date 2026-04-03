FROM python:3.11-slim
WORKDIR /app

# Install Node.js + Claude CLI (needed by simmer-sdk judge board)
# The bundled CLI in claude-agent-sdk has a broken subprocess transport;
# installing the system CLI lets simmer-sdk's get_cli_path() find a working binary.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install orrery-relay (shared LLM client SDK)
COPY packages/orrery-relay/ /tmp/orrery-relay/
RUN pip install --no-cache-dir /tmp/orrery-relay/ && rm -rf /tmp/orrery-relay/

# Install simmer-sdk (internal dependency)
# Clone simmer-sdk alongside this repo, or copy it into worker/simmer-sdk/
COPY worker/simmer-sdk/ /tmp/simmer-sdk/
RUN pip install --no-cache-dir /tmp/simmer-sdk/ && rm -rf /tmp/simmer-sdk/

COPY worker/pyproject.toml .
RUN pip install --no-cache-dir .
COPY worker/src/ src/
CMD ["python", "-m", "src.main"]
