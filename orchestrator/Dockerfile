FROM python:3.13-slim
WORKDIR /app

# Install orrery-relay (shared LLM client SDK)
COPY packages/orrery-relay/ /tmp/orrery-relay/
RUN pip install --no-cache-dir /tmp/orrery-relay/ && rm -rf /tmp/orrery-relay/

COPY orchestrator/pyproject.toml .
RUN pip install --no-cache-dir .
COPY orchestrator/src/ src/
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
