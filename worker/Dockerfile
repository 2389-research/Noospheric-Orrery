FROM python:3.11-slim
WORKDIR /app

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
