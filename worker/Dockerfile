FROM python:3.11-slim
WORKDIR /app

# Install simmer-sdk first (internal dependency)
# Clone simmer-sdk alongside this repo, or copy it into worker/simmer-sdk/
COPY simmer-sdk/ /tmp/simmer-sdk/
RUN pip install --no-cache-dir /tmp/simmer-sdk/ && rm -rf /tmp/simmer-sdk/

COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY src/ src/
CMD ["python", "-m", "src.main"]
