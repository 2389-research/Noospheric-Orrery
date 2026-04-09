# ABOUTME: Docker build for the orchestrator (FastAPI REST API).
# ABOUTME: Uses uv for dependency management with frozen lockfile.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Disable numba JIT — prevents SIGILL on ARM Docker
ENV NUMBA_DISABLE_JIT=1

# Mirror repo layout so ../packages/orrery-relay resolves from pyproject.toml
COPY packages/orrery-relay/ /app/packages/orrery-relay/

WORKDIR /app/orchestrator

# Install dependencies from lockfile
COPY orchestrator/pyproject.toml orchestrator/uv.lock ./
RUN uv sync --frozen --no-cache --no-dev

# Copy application code + general specs
COPY orchestrator/src/ src/
COPY orchestrator/specs/ specs/

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
