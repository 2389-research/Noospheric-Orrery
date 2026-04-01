# orrery-relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a shared LLM client SDK (`orrery-relay`) that supports both direct AWS Bedrock and the Bedrock Gateway proxy, then migrate all Anthropic client usage in orchestrator and worker to use it.

**Architecture:** A new Python package at `packages/orrery-relay/` with a `Relay` class that wraps client creation, model ID mapping, retry logic, structured logging, and usage tracking callbacks. Both orchestrator and worker depend on it via path reference. Consumers always use friendly model names (`claude-sonnet-4-6`); the relay translates to Bedrock format when needed.

**Tech Stack:** Python 3.11+, `anthropic[bedrock]` SDK, `pytest` + `pytest-asyncio`, `uv` for package management.

**Spec:** `docs/superpowers/specs/2026-03-31-orrery-relay-design.md`

---

### Task 1: Scaffold orrery-relay package + types

**Files:**
- Create: `packages/orrery-relay/pyproject.toml`
- Create: `packages/orrery-relay/src/orrery_relay/__init__.py`
- Create: `packages/orrery-relay/src/orrery_relay/types.py`
- Create: `packages/orrery-relay/tests/__init__.py`
- Create: `packages/orrery-relay/tests/test_types.py`

- [ ] **Step 1: Write the failing test for RelayResponse and UsageEvent**

```python
# packages/orrery-relay/tests/test_types.py
# ABOUTME: Tests for orrery-relay type dataclasses.
# ABOUTME: Verifies RelayResponse and UsageEvent construction and field access.

from unittest.mock import MagicMock


def test_relay_response_fields():
    from orrery_relay.types import RelayResponse

    mock_message = MagicMock()
    resp = RelayResponse(
        raw=mock_message,
        text="Hello world",
        input_tokens=10,
        output_tokens=5,
        model="claude-sonnet-4-6",
        latency_ms=123.4,
        backend="gateway",
    )
    assert resp.text == "Hello world"
    assert resp.input_tokens == 10
    assert resp.output_tokens == 5
    assert resp.model == "claude-sonnet-4-6"
    assert resp.latency_ms == 123.4
    assert resp.backend == "gateway"
    assert resp.raw is mock_message


def test_usage_event_fields():
    from orrery_relay.types import UsageEvent

    event = UsageEvent(
        model="claude-haiku-4-5",
        backend="bedrock",
        input_tokens=100,
        output_tokens=200,
        latency_ms=500.0,
        timestamp="2026-03-31T12:00:00Z",
        retries=1,
    )
    assert event.model == "claude-haiku-4-5"
    assert event.backend == "bedrock"
    assert event.retries == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/orrery-relay && uv run pytest tests/test_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orrery_relay'`

- [ ] **Step 3: Create pyproject.toml**

```toml
# packages/orrery-relay/pyproject.toml
[project]
name = "orrery-relay"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic[bedrock]>=0.40.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[tool.hatch.build.targets.wheel]
packages = ["src/orrery_relay"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 4: Create __init__.py**

```python
# packages/orrery-relay/src/orrery_relay/__init__.py
# ABOUTME: Public API for orrery-relay — shared LLM client SDK.
# ABOUTME: Supports both direct AWS Bedrock and the Bedrock Gateway proxy.

from .types import RelayResponse, UsageEvent

__all__ = ["RelayResponse", "UsageEvent"]
```

- [ ] **Step 5: Create types.py**

```python
# packages/orrery-relay/src/orrery_relay/types.py
# ABOUTME: Data types for orrery-relay: response wrappers and usage events.
# ABOUTME: RelayResponse wraps Anthropic Message; UsageEvent fires on each completion.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RelayResponse:
    """Wrapper around an Anthropic Message with convenience fields."""

    raw: Any  # anthropic.types.Message — typed as Any to avoid import at definition time
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: float
    backend: str


@dataclass
class UsageEvent:
    """Fired after each successful completion for external tracking."""

    model: str
    backend: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    timestamp: str
    retries: int
```

- [ ] **Step 6: Create empty tests/__init__.py**

```python
# packages/orrery-relay/tests/__init__.py
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd packages/orrery-relay && uv sync --dev && uv run pytest tests/test_types.py -v`
Expected: 2 passed

- [ ] **Step 8: Commit**

```bash
git add packages/orrery-relay/
git commit -m "feat: scaffold orrery-relay package with types"
```

---

### Task 2: Backend factory — client creation + model mapping

**Files:**
- Create: `packages/orrery-relay/src/orrery_relay/backends.py`
- Create: `packages/orrery-relay/tests/test_backends.py`

- [ ] **Step 1: Write failing tests for backend factory**

```python
# packages/orrery-relay/tests/test_backends.py
# ABOUTME: Tests for backend client factory and model ID mapping.
# ABOUTME: Verifies gateway/bedrock client creation and model name translation.

from unittest.mock import patch, MagicMock


def test_create_async_client_gateway():
    from orrery_relay.backends import create_async_client

    with patch("orrery_relay.backends.AsyncAnthropic") as mock_cls:
        client = create_async_client(
            backend="gateway",
            gateway_url="https://gw.example.com",
            gateway_api_key="test-key",
        )
        mock_cls.assert_called_once_with(
            api_key="test-key",
            base_url="https://gw.example.com",
        )


def test_create_async_client_bedrock():
    from orrery_relay.backends import create_async_client

    with patch("orrery_relay.backends.AsyncAnthropicBedrock") as mock_cls:
        client = create_async_client(
            backend="bedrock",
            aws_access_key="ak",
            aws_secret_key="sk",
            aws_region="us-west-2",
        )
        mock_cls.assert_called_once_with(
            aws_access_key="ak",
            aws_secret_key="sk",
            aws_region="us-west-2",
        )


def test_create_sync_client_gateway():
    from orrery_relay.backends import create_sync_client

    with patch("orrery_relay.backends.Anthropic") as mock_cls:
        client = create_sync_client(
            backend="gateway",
            gateway_url="https://gw.example.com",
            gateway_api_key="test-key",
        )
        mock_cls.assert_called_once_with(
            api_key="test-key",
            base_url="https://gw.example.com",
        )


def test_create_sync_client_bedrock():
    from orrery_relay.backends import create_sync_client

    with patch("orrery_relay.backends.AnthropicBedrock") as mock_cls:
        client = create_sync_client(
            backend="bedrock",
            aws_access_key="ak",
            aws_secret_key="sk",
            aws_region="us-east-1",
        )
        mock_cls.assert_called_once_with(
            aws_access_key="ak",
            aws_secret_key="sk",
            aws_region="us-east-1",
        )


def test_map_model_gateway_passes_through():
    from orrery_relay.backends import map_model_id

    assert map_model_id("claude-sonnet-4-6", "gateway") == "claude-sonnet-4-6"
    assert map_model_id("claude-haiku-4-5", "gateway") == "claude-haiku-4-5"


def test_map_model_bedrock_translates():
    from orrery_relay.backends import map_model_id

    assert map_model_id("claude-sonnet-4-6", "bedrock") == "us.anthropic.claude-sonnet-4-20250514-v1:0"
    assert map_model_id("claude-haiku-4-5", "bedrock") == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert map_model_id("claude-opus-4-6", "bedrock") == "us.anthropic.claude-opus-4-6-v1:0"


def test_map_model_bedrock_passthrough_for_already_bedrock_ids():
    from orrery_relay.backends import map_model_id

    bedrock_id = "us.anthropic.claude-sonnet-4-20250514-v1:0"
    assert map_model_id(bedrock_id, "bedrock") == bedrock_id


def test_create_async_client_raises_on_unknown_backend():
    from orrery_relay.backends import create_async_client
    import pytest

    with pytest.raises(ValueError, match="Unknown backend"):
        create_async_client(backend="unknown")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/orrery-relay && uv run pytest tests/test_backends.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orrery_relay.backends'`

- [ ] **Step 3: Implement backends.py**

```python
# packages/orrery-relay/src/orrery_relay/backends.py
# ABOUTME: Client factory and model ID mapping for Bedrock and Gateway backends.
# ABOUTME: Creates the right Anthropic client type and translates model names.

from __future__ import annotations

from anthropic import (
    Anthropic,
    AnthropicBedrock,
    AsyncAnthropic,
    AsyncAnthropicBedrock,
)

BEDROCK_MODEL_MAP = {
    "claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "claude-sonnet-4-5": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "claude-haiku-4-5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-opus-4-6": "us.anthropic.claude-opus-4-6-v1:0",
}


def map_model_id(model: str, backend: str) -> str:
    """Translate a friendly model name to the backend-specific ID."""
    if backend != "bedrock":
        return model
    # Already a Bedrock ID — pass through
    if "us.anthropic." in model:
        return model
    return BEDROCK_MODEL_MAP.get(model, model)


def create_async_client(
    backend: str = "gateway",
    gateway_url: str = "",
    gateway_api_key: str = "",
    aws_access_key: str = "",
    aws_secret_key: str = "",
    aws_region: str = "us-east-1",
) -> AsyncAnthropic | AsyncAnthropicBedrock:
    """Create the appropriate async Anthropic client for the chosen backend."""
    if backend == "gateway":
        return AsyncAnthropic(api_key=gateway_api_key, base_url=gateway_url)
    elif backend == "bedrock":
        return AsyncAnthropicBedrock(
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
            aws_region=aws_region,
        )
    else:
        raise ValueError(f"Unknown backend: {backend!r}. Use 'gateway' or 'bedrock'.")


def create_sync_client(
    backend: str = "gateway",
    gateway_url: str = "",
    gateway_api_key: str = "",
    aws_access_key: str = "",
    aws_secret_key: str = "",
    aws_region: str = "us-east-1",
) -> Anthropic | AnthropicBedrock:
    """Create the appropriate sync Anthropic client for the chosen backend."""
    if backend == "gateway":
        return Anthropic(api_key=gateway_api_key, base_url=gateway_url)
    elif backend == "bedrock":
        return AnthropicBedrock(
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
            aws_region=aws_region,
        )
    else:
        raise ValueError(f"Unknown backend: {backend!r}. Use 'gateway' or 'bedrock'.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/orrery-relay && uv run pytest tests/test_backends.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add packages/orrery-relay/src/orrery_relay/backends.py packages/orrery-relay/tests/test_backends.py
git commit -m "feat(orrery-relay): backend factory with model ID mapping"
```

---

### Task 3: Retry logic

**Files:**
- Create: `packages/orrery-relay/src/orrery_relay/retry.py`
- Create: `packages/orrery-relay/tests/test_retry.py`

- [ ] **Step 1: Write failing tests for retry**

```python
# packages/orrery-relay/tests/test_retry.py
# ABOUTME: Tests for exponential backoff retry logic.
# ABOUTME: Verifies retry on transient errors, no retry on permanent errors.

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from anthropic import APIStatusError


def _make_api_status_error(status_code: int):
    """Create a realistic APIStatusError for testing."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = {}
    return APIStatusError(
        message=f"Error {status_code}",
        response=mock_response,
        body=None,
    )


@pytest.mark.asyncio
async def test_retry_succeeds_after_transient_failure():
    from orrery_relay.retry import with_retry

    call_count = 0

    async def flaky_fn():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise _make_api_status_error(429)
        return "success"

    result = await with_retry(flaky_fn, max_retries=3, base_delay=0.01, max_delay=0.1)
    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_raises_on_permanent_error():
    from orrery_relay.retry import with_retry

    async def bad_request():
        raise _make_api_status_error(400)

    with pytest.raises(APIStatusError):
        await with_retry(bad_request, max_retries=3, base_delay=0.01, max_delay=0.1)


@pytest.mark.asyncio
async def test_retry_exhausted_raises():
    from orrery_relay.retry import with_retry

    async def always_fails():
        raise _make_api_status_error(500)

    with pytest.raises(APIStatusError):
        await with_retry(always_fails, max_retries=2, base_delay=0.01, max_delay=0.1)


@pytest.mark.asyncio
async def test_retry_respects_retry_after_header():
    from orrery_relay.retry import with_retry

    call_count = 0

    async def rate_limited():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            err = _make_api_status_error(429)
            err.response.headers = {"retry-after": "0.01"}
            raise err
        return "ok"

    result = await with_retry(rate_limited, max_retries=3, base_delay=0.01, max_delay=0.1)
    assert result == "ok"
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_retries_on_overloaded():
    from orrery_relay.retry import with_retry

    call_count = 0

    async def overloaded():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_api_status_error(529)
        return "recovered"

    result = await with_retry(overloaded, max_retries=3, base_delay=0.01, max_delay=0.1)
    assert result == "recovered"


def test_retry_sync_succeeds_after_transient_failure():
    from orrery_relay.retry import with_retry_sync

    call_count = 0

    def flaky_fn():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise _make_api_status_error(500)
        return "sync_success"

    result = with_retry_sync(flaky_fn, max_retries=3, base_delay=0.01, max_delay=0.1)
    assert result == "sync_success"
    assert call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/orrery-relay && uv run pytest tests/test_retry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orrery_relay.retry'`

- [ ] **Step 3: Implement retry.py**

```python
# packages/orrery-relay/src/orrery_relay/retry.py
# ABOUTME: Exponential backoff with jitter for transient API errors.
# ABOUTME: Retries on 429/500/502/503/529; raises immediately on 400/401/404.

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Awaitable, Callable, TypeVar

from anthropic import APIStatusError

logger = logging.getLogger("orrery_relay")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

T = TypeVar("T")


def _compute_delay(
    attempt: int,
    base_delay: float,
    max_delay: float,
    retry_after: float | None,
) -> float:
    """Calculate delay for the given retry attempt."""
    if retry_after is not None:
        return retry_after
    delay = base_delay * (2 ** (attempt - 1))
    # Add jitter: 0–25% of the delay
    delay += random.uniform(0, delay * 0.25)
    return min(delay, max_delay)


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> T:
    """Call fn with exponential backoff retry on transient errors."""
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return await fn()
        except APIStatusError as e:
            if e.response.status_code not in RETRYABLE_STATUS_CODES:
                raise
            last_error = e
            if attempt == max_retries:
                raise

            retry_after_header = e.response.headers.get("retry-after")
            retry_after = float(retry_after_header) if retry_after_header else None
            delay = _compute_delay(attempt, base_delay, max_delay, retry_after)

            logger.warning(
                "retry attempt=%d/%d status=%d delay=%.1fs",
                attempt + 1,
                max_retries,
                e.response.status_code,
                delay,
            )
            await asyncio.sleep(delay)

    # Should not reach here, but satisfy type checker
    raise last_error  # type: ignore[misc]


def with_retry_sync(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> T:
    """Synchronous version of with_retry."""
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except APIStatusError as e:
            if e.response.status_code not in RETRYABLE_STATUS_CODES:
                raise
            last_error = e
            if attempt == max_retries:
                raise

            retry_after_header = e.response.headers.get("retry-after")
            retry_after = float(retry_after_header) if retry_after_header else None
            delay = _compute_delay(attempt, base_delay, max_delay, retry_after)

            logger.warning(
                "retry attempt=%d/%d status=%d delay=%.1fs",
                attempt + 1,
                max_retries,
                e.response.status_code,
                delay,
            )
            time.sleep(delay)

    raise last_error  # type: ignore[misc]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/orrery-relay && uv run pytest tests/test_retry.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add packages/orrery-relay/src/orrery_relay/retry.py packages/orrery-relay/tests/test_retry.py
git commit -m "feat(orrery-relay): retry logic with exponential backoff"
```

---

### Task 4: Relay class — the main interface

**Files:**
- Create: `packages/orrery-relay/src/orrery_relay/relay.py`
- Create: `packages/orrery-relay/tests/test_relay.py`
- Modify: `packages/orrery-relay/src/orrery_relay/__init__.py`

- [ ] **Step 1: Write failing tests for Relay**

```python
# packages/orrery-relay/tests/test_relay.py
# ABOUTME: Tests for the Relay class — the main orrery-relay interface.
# ABOUTME: Verifies complete(), complete_sync(), from_env(), usage callbacks.

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_anthropic_message(text="Hello", input_tokens=10, output_tokens=5):
    """Create a mock Anthropic Message object."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return msg


@pytest.mark.asyncio
async def test_relay_complete_gateway():
    from orrery_relay import Relay

    mock_msg = _mock_anthropic_message("response text", 15, 8)
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    with patch("orrery_relay.relay.create_async_client", return_value=mock_client):
        relay = Relay(backend="gateway", gateway_url="https://gw.test", gateway_api_key="key")
        resp = await relay.complete(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=100,
        )

    assert resp.text == "response text"
    assert resp.input_tokens == 15
    assert resp.output_tokens == 8
    assert resp.model == "claude-sonnet-4-6"
    assert resp.backend == "gateway"
    assert resp.latency_ms >= 0
    # Verify the model was passed through (gateway doesn't map)
    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_relay_complete_bedrock_maps_model():
    from orrery_relay import Relay

    mock_msg = _mock_anthropic_message()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    with patch("orrery_relay.relay.create_async_client", return_value=mock_client):
        relay = Relay(backend="bedrock", aws_access_key="ak", aws_secret_key="sk")
        await relay.complete(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=100,
        )

    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "us.anthropic.claude-sonnet-4-20250514-v1:0"


@pytest.mark.asyncio
async def test_relay_complete_passes_system_and_temperature():
    from orrery_relay import Relay

    mock_msg = _mock_anthropic_message()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    with patch("orrery_relay.relay.create_async_client", return_value=mock_client):
        relay = Relay(backend="gateway", gateway_url="https://gw.test", gateway_api_key="key")
        await relay.complete(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=100,
            system="You are helpful.",
            temperature=0.5,
        )

    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["system"] == "You are helpful."
    assert call_kwargs["temperature"] == 0.5


@pytest.mark.asyncio
async def test_relay_complete_fires_usage_callback():
    from orrery_relay import Relay

    mock_msg = _mock_anthropic_message(input_tokens=20, output_tokens=30)
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    usage_events = []

    async def capture_usage(event):
        usage_events.append(event)

    with patch("orrery_relay.relay.create_async_client", return_value=mock_client):
        relay = Relay(
            backend="gateway", gateway_url="https://gw.test", gateway_api_key="key",
            on_usage=capture_usage,
        )
        await relay.complete(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=100,
        )

    assert len(usage_events) == 1
    assert usage_events[0].model == "claude-sonnet-4-6"
    assert usage_events[0].input_tokens == 20
    assert usage_events[0].output_tokens == 30
    assert usage_events[0].backend == "gateway"
    assert usage_events[0].retries == 0


def test_relay_complete_sync():
    from orrery_relay import Relay

    mock_msg = _mock_anthropic_message("sync response")
    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=mock_msg)

    with patch("orrery_relay.relay.create_sync_client", return_value=mock_client):
        relay = Relay(backend="gateway", gateway_url="https://gw.test", gateway_api_key="key")
        resp = relay.complete_sync(
            model="claude-haiku-4-5",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=50,
        )

    assert resp.text == "sync response"
    assert resp.backend == "gateway"


def test_relay_from_env_gateway(monkeypatch):
    from orrery_relay import Relay

    monkeypatch.setenv("ANTHROPIC_BACKEND", "gateway")
    monkeypatch.setenv("GATEWAY_URL", "https://gw.env.test")
    monkeypatch.setenv("GATEWAY_API_KEY", "env-key")

    with patch("orrery_relay.relay.create_async_client") as mock_create:
        relay = Relay.from_env()
        assert relay._backend == "gateway"
        assert relay._gateway_url == "https://gw.env.test"


def test_relay_from_env_bedrock(monkeypatch):
    from orrery_relay import Relay

    monkeypatch.setenv("ANTHROPIC_BACKEND", "bedrock")
    monkeypatch.setenv("AWS_ACCESS_KEY", "env-ak")
    monkeypatch.setenv("AWS_SECRET_KEY", "env-sk")
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    with patch("orrery_relay.relay.create_async_client") as mock_create:
        relay = Relay.from_env()
        assert relay._backend == "bedrock"
        assert relay._aws_region == "us-west-2"


@pytest.mark.asyncio
async def test_relay_complete_passes_kwargs_through():
    from orrery_relay import Relay

    mock_msg = _mock_anthropic_message()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    with patch("orrery_relay.relay.create_async_client", return_value=mock_client):
        relay = Relay(backend="gateway", gateway_url="https://gw.test", gateway_api_key="key")
        await relay.complete(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=100,
            tools=[{"name": "my_tool", "description": "does stuff", "input_schema": {}}],
        )

    call_kwargs = mock_client.messages.create.call_args[1]
    assert len(call_kwargs["tools"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/orrery-relay && uv run pytest tests/test_relay.py -v`
Expected: FAIL — `ImportError: cannot import name 'Relay' from 'orrery_relay'`

- [ ] **Step 3: Implement relay.py**

```python
# packages/orrery-relay/src/orrery_relay/relay.py
# ABOUTME: The Relay class — main interface for orrery-relay.
# ABOUTME: Wraps client creation, model mapping, retry, logging, and usage tracking.

from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .backends import create_async_client, create_sync_client, map_model_id
from .retry import with_retry, with_retry_sync
from .types import RelayResponse, UsageEvent

logger = logging.getLogger("orrery_relay")


class Relay:
    """Shared LLM client that supports both Bedrock and Gateway backends."""

    def __init__(
        self,
        backend: str = "gateway",
        # Gateway config
        gateway_url: str = "",
        gateway_api_key: str = "",
        # Bedrock config
        aws_access_key: str = "",
        aws_secret_key: str = "",
        aws_region: str = "us-east-1",
        # Resilience
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        # Observability
        on_usage: Callable[[UsageEvent], Awaitable[None]] | None = None,
    ) -> None:
        self._backend = backend
        self._gateway_url = gateway_url
        self._gateway_api_key = gateway_api_key
        self._aws_access_key = aws_access_key
        self._aws_secret_key = aws_secret_key
        self._aws_region = aws_region
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._on_usage = on_usage

        self._async_client = create_async_client(
            backend=backend,
            gateway_url=gateway_url,
            gateway_api_key=gateway_api_key,
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
            aws_region=aws_region,
        )
        self._sync_client: Any = None  # created lazily

    @classmethod
    def from_env(cls, **overrides: Any) -> Relay:
        """Create a Relay from environment variables."""
        log_level = os.environ.get("RELAY_LOG_LEVEL", "INFO")
        logging.getLogger("orrery_relay").setLevel(getattr(logging, log_level.upper(), logging.INFO))

        kwargs: dict[str, Any] = {
            "backend": os.environ.get("ANTHROPIC_BACKEND", "gateway"),
            "gateway_url": os.environ.get("GATEWAY_URL", ""),
            "gateway_api_key": os.environ.get("GATEWAY_API_KEY", ""),
            "aws_access_key": os.environ.get("AWS_ACCESS_KEY", ""),
            "aws_secret_key": os.environ.get("AWS_SECRET_KEY", ""),
            "aws_region": os.environ.get("AWS_REGION", "us-east-1"),
            "max_retries": int(os.environ.get("RELAY_MAX_RETRIES", "3")),
            "base_delay": float(os.environ.get("RELAY_BASE_DELAY", "1.0")),
            "max_delay": float(os.environ.get("RELAY_MAX_DELAY", "30.0")),
        }
        kwargs.update(overrides)
        return cls(**kwargs)

    @classmethod
    def from_settings(cls, settings: Any, **overrides: Any) -> Relay:
        """Create a Relay from an Orrery Settings dataclass."""
        kwargs: dict[str, Any] = {
            "backend": getattr(settings, "anthropic_backend", "gateway"),
            "gateway_url": getattr(settings, "gateway_url", ""),
            "gateway_api_key": getattr(settings, "gateway_api_key", ""),
            "aws_access_key": getattr(settings, "aws_access_key", ""),
            "aws_secret_key": getattr(settings, "aws_secret_key", ""),
            "aws_region": getattr(settings, "aws_region", "us-east-1"),
        }
        kwargs.update(overrides)
        return cls(**kwargs)

    async def complete(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        system: str | None = None,
        temperature: float | None = None,
        tools: list[dict] | None = None,
        tool_choice: dict | None = None,
        **kwargs: Any,
    ) -> RelayResponse:
        """Send a completion request with retry and logging."""
        mapped_model = map_model_id(model, self._backend)

        call_kwargs: dict[str, Any] = {
            "model": mapped_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system is not None:
            call_kwargs["system"] = system
        if temperature is not None:
            call_kwargs["temperature"] = temperature
        if tools is not None:
            call_kwargs["tools"] = tools
        if tool_choice is not None:
            call_kwargs["tool_choice"] = tool_choice
        call_kwargs.update(kwargs)

        retries_used = 0
        start = time.monotonic()

        async def _call() -> Any:
            return await self._async_client.messages.create(**call_kwargs)

        try:
            raw = await with_retry(
                _call,
                max_retries=self._max_retries,
                base_delay=self._base_delay,
                max_delay=self._max_delay,
            )
        except Exception:
            elapsed = (time.monotonic() - start) * 1000
            logger.error("failed model=%s status=error latency=%.0fms", model, elapsed)
            raise

        elapsed = (time.monotonic() - start) * 1000
        text = raw.content[0].text if raw.content else ""
        input_tokens = raw.usage.input_tokens
        output_tokens = raw.usage.output_tokens

        logger.info(
            "complete model=%s backend=%s tokens=%d/%d latency=%.0fms",
            model, self._backend, input_tokens, output_tokens, elapsed,
        )

        response = RelayResponse(
            raw=raw,
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            latency_ms=elapsed,
            backend=self._backend,
        )

        if self._on_usage:
            from datetime import datetime, timezone

            event = UsageEvent(
                model=model,
                backend=self._backend,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=elapsed,
                timestamp=datetime.now(timezone.utc).isoformat(),
                retries=retries_used,
            )
            await self._on_usage(event)

        return response

    def complete_sync(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        system: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> RelayResponse:
        """Synchronous completion with retry and logging."""
        if self._sync_client is None:
            self._sync_client = create_sync_client(
                backend=self._backend,
                gateway_url=self._gateway_url,
                gateway_api_key=self._gateway_api_key,
                aws_access_key=self._aws_access_key,
                aws_secret_key=self._aws_secret_key,
                aws_region=self._aws_region,
            )

        mapped_model = map_model_id(model, self._backend)

        call_kwargs: dict[str, Any] = {
            "model": mapped_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system is not None:
            call_kwargs["system"] = system
        if temperature is not None:
            call_kwargs["temperature"] = temperature
        call_kwargs.update(kwargs)

        start = time.monotonic()

        def _call() -> Any:
            return self._sync_client.messages.create(**call_kwargs)

        raw = with_retry_sync(
            _call,
            max_retries=self._max_retries,
            base_delay=self._base_delay,
            max_delay=self._max_delay,
        )

        elapsed = (time.monotonic() - start) * 1000
        text = raw.content[0].text if raw.content else ""

        logger.info(
            "complete_sync model=%s backend=%s tokens=%d/%d latency=%.0fms",
            model, self._backend, raw.usage.input_tokens, raw.usage.output_tokens, elapsed,
        )

        return RelayResponse(
            raw=raw,
            text=text,
            input_tokens=raw.usage.input_tokens,
            output_tokens=raw.usage.output_tokens,
            model=model,
            latency_ms=elapsed,
            backend=self._backend,
        )
```

- [ ] **Step 4: Update __init__.py to export Relay**

Replace the contents of `packages/orrery-relay/src/orrery_relay/__init__.py` with:

```python
# packages/orrery-relay/src/orrery_relay/__init__.py
# ABOUTME: Public API for orrery-relay — shared LLM client SDK.
# ABOUTME: Supports both direct AWS Bedrock and the Bedrock Gateway proxy.

from .relay import Relay
from .types import RelayResponse, UsageEvent

__all__ = ["Relay", "RelayResponse", "UsageEvent"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd packages/orrery-relay && uv run pytest tests/ -v`
Expected: All tests pass (types + backends + retry + relay)

- [ ] **Step 6: Commit**

```bash
git add packages/orrery-relay/src/orrery_relay/relay.py packages/orrery-relay/src/orrery_relay/__init__.py packages/orrery-relay/tests/test_relay.py
git commit -m "feat(orrery-relay): Relay class with complete, complete_sync, from_env"
```

---

### Task 5: Update orchestrator config.py

**Files:**
- Modify: `orchestrator/src/config.py:1-36`
- Modify: `orchestrator/pyproject.toml:1-29`

- [ ] **Step 1: Update orchestrator/src/config.py**

Replace the full file with:

```python
# orchestrator/src/config.py
# ABOUTME: Application settings loaded from environment variables.
# ABOUTME: Supports both gateway and bedrock backends via ANTHROPIC_BACKEND env var.

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_backend: str = "gateway"
    gateway_url: str = ""
    gateway_api_key: str = ""
    aws_access_key: str = ""
    aws_secret_key: str = ""
    aws_region: str = "us-east-1"
    classification_model: str = "claude-sonnet-4-6"
    extraction_model: str = "claude-haiku-4-5"
    general_spec_threshold: int = 10
    domain_spec_threshold: int = 20
    simmer_iterations: int = 5
    chunk_size: int = 2000
    worker_poll_interval: int = 5
    db_path: str = "/data/orrery.db"
    documents_dir: str = "/data/documents"
    specs_dir: str = "/data/specs"


def get_settings() -> Settings:
    return Settings(
        anthropic_backend=os.environ.get("ANTHROPIC_BACKEND", "gateway"),
        gateway_url=os.environ.get("GATEWAY_URL", ""),
        gateway_api_key=os.environ.get("GATEWAY_API_KEY", ""),
        aws_access_key=os.environ.get("AWS_ACCESS_KEY", ""),
        aws_secret_key=os.environ.get("AWS_SECRET_KEY", ""),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        classification_model=os.environ.get("CLASSIFICATION_MODEL", "claude-sonnet-4-6"),
        extraction_model=os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5"),
        general_spec_threshold=int(os.environ.get("GENERAL_SPEC_THRESHOLD", "10")),
        domain_spec_threshold=int(os.environ.get("DOMAIN_SPEC_THRESHOLD", "20")),
        simmer_iterations=int(os.environ.get("SIMMER_ITERATIONS", "5")),
        chunk_size=int(os.environ.get("CHUNK_SIZE", "2000")),
        worker_poll_interval=int(os.environ.get("WORKER_POLL_INTERVAL", "5")),
        db_path=os.environ.get("DB_PATH", "/data/orrery.db"),
        documents_dir=os.environ.get("DOCUMENTS_DIR", "/data/documents"),
        specs_dir=os.environ.get("SPECS_DIR", "/data/specs"),
    )
```

- [ ] **Step 2: Add orrery-relay dependency to orchestrator/pyproject.toml**

Add to the `dependencies` list in `orchestrator/pyproject.toml`:

```
    "orrery-relay",
```

And add a `[tool.uv.sources]` section:

```toml
[tool.uv.sources]
orrery-relay = { path = "../packages/orrery-relay" }
```

- [ ] **Step 3: Run `uv sync` in orchestrator to verify dependency resolves**

Run: `cd orchestrator && uv sync --dev`
Expected: resolves without error

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/config.py orchestrator/pyproject.toml
git commit -m "refactor(orchestrator): update config for dual-backend support"
```

---

### Task 6: Migrate orchestrator pipeline functions (classifier, extractor, subdomain_discovery)

**Files:**
- Modify: `orchestrator/src/pipeline/classifier.py:1-46`
- Modify: `orchestrator/src/pipeline/extractor.py:1-47`
- Modify: `orchestrator/src/pipeline/subdomain_discovery.py:1-150`

- [ ] **Step 1: Update classifier.py — change client param to relay**

Replace lines 1-2 and the function signature/body at lines 28-46:

```python
# orchestrator/src/pipeline/classifier.py (full file)
# ABOUTME: Classify documents into domains using an LLM.
# ABOUTME: Takes a Relay instance and returns primary/secondary domain paths.

import json
from orrery_relay import Relay

CLASSIFICATION_PROMPT = """You are a document classifier for a knowledge graph system. Given a document excerpt and existing domain taxonomy, classify the document.

Existing taxonomy:
{taxonomy}

Document:
{excerpt}

Respond with JSON only:
{{
    "primary_domain": "region/parent/subdomain",
    "secondary_domains": ["other/domains"],
    "confidence": 0.0-1.0
}}

Rules:
- Use existing domains when they fit
- You CAN and SHOULD create new domain paths that don't exist in the taxonomy if the document covers a topic not well represented by existing domains
- Domain paths are hierarchical: region/parent/subdomain (e.g., business/technology/ai, business/legal/contracts)
- A document can have 1 primary and 0-3 secondary domains
- Be specific — prefer "region/parent/specific_topic" over just "region/parent" (e.g., "business/fundraising/seed_round", "science/biology/genetics", "hobby/miniature_painting/techniques")
- New domains are automatically added to the taxonomy, so don't hesitate to propose them
"""

async def classify_document(
    relay: Relay,
    title: str,
    excerpt: str,
    existing_taxonomy: list[str],
    model: str,
) -> dict:
    taxonomy_str = "\n".join(f"  - {d}" for d in existing_taxonomy) if existing_taxonomy else "  (empty — propose new domains)"

    response = await relay.complete(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": CLASSIFICATION_PROMPT.format(taxonomy=taxonomy_str, excerpt=excerpt)}],
    )

    text = response.text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)
```

- [ ] **Step 2: Update extractor.py — change client param to relay**

```python
# orchestrator/src/pipeline/extractor.py (full file)
# ABOUTME: Extract entities from document chunks using an LLM and an extraction spec.
# ABOUTME: Takes a Relay instance and returns deduplicated entity lists.

import json
from orrery_relay import Relay

EXTRACTION_WRAPPER = """You are an entity extraction system. Follow the extraction spec below exactly.

EXTRACTION SPEC:
{spec}

TEXT TO EXTRACT FROM:
{chunk_text}

Respond with JSON only:
{{
    "entities": [
        {{"name": "entity name", "type": "EntityType"}}
    ]
}}

Rules:
- Only extract entities explicitly mentioned in the text
- Do not hallucinate or infer entities not present
- Use the entity types defined in the spec
- Normalize names: lowercase, strip extra whitespace
"""

async def extract_entities_from_chunk(relay: Relay, chunk_text: str, spec: str, model: str) -> list[dict]:
    response = await relay.complete(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": EXTRACTION_WRAPPER.format(spec=spec, chunk_text=chunk_text)}],
    )
    text = response.text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text).get("entities", [])

async def extract_document(relay: Relay, chunks: list[dict], spec: str, model: str) -> list[dict]:
    all_entities = []
    seen = set()
    for chunk in chunks:
        entities = await extract_entities_from_chunk(relay=relay, chunk_text=chunk["text"], spec=spec, model=model)
        for entity in entities:
            key = (entity["name"].lower().strip(), entity["type"])
            if key not in seen:
                seen.add(key)
                entity["chunk_id"] = chunk.get("id")
                all_entities.append(entity)
    return all_entities
```

- [ ] **Step 3: Update subdomain_discovery.py — change client param to relay**

```python
# orchestrator/src/pipeline/subdomain_discovery.py (full file)
# ABOUTME: Lightweight subdomain discovery from extracted entities.
# ABOUTME: Additive — docs gain subdomains, never lose existing domains.

import json
import sqlite3
from orrery_relay import Relay

SUBDOMAIN_PROMPT = """You are refining the domain taxonomy for a knowledge graph. A document has already been classified into these domains:

Current domains: {current_domains}

The document has these extracted entities:
{entities}

The existing taxonomy has these domains:
{taxonomy}

Based on the entity profile, should this document be tagged with any MORE SPECIFIC subdomains? Only propose subdomains that are clearly warranted by the entities.

Rules:
- Only ADD subdomains — never remove existing domain assignments
- Subdomains must be children of existing domains (e.g., business/fundraising → business/fundraising/seed_round)
- Only propose if the entities clearly indicate a specific subtopic
- If no subdomains are warranted, return an empty list

Respond with JSON only:
{{
    "new_subdomains": ["domain/path/subdomain", ...]
}}
"""


async def discover_subdomains_for_document(
    relay: Relay,
    model: str,
    conn: sqlite3.Connection,
    document_id: str,
) -> list[str]:
    """Check if a doc should get more specific subdomains based on its entities."""

    # Get current domains
    current = conn.execute(
        "SELECT domain_path FROM document_domains WHERE document_id = ?",
        (document_id,),
    ).fetchall()
    current_domains = [r[0] for r in current]

    if not current_domains:
        return []

    # Get extracted entities for this doc
    entities = conn.execute(
        """SELECT DISTINCT e.canonical_name, e.type FROM entities e
           JOIN entity_sources es ON e.id = es.entity_id
           WHERE es.document_id = ?""",
        (document_id,),
    ).fetchall()

    if len(entities) < 3:
        return []  # Not enough entities to discover subdomains

    entities_str = "\n".join(f"- {e[0]} ({e[1]})" for e in entities)

    # Get existing taxonomy
    taxonomy = conn.execute("SELECT path FROM domains ORDER BY path").fetchall()
    taxonomy_str = "\n".join(f"- {t[0]}" for t in taxonomy)

    response = await relay.complete(
        model=model,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": SUBDOMAIN_PROMPT.format(
                current_domains=", ".join(current_domains),
                entities=entities_str,
                taxonomy=taxonomy_str,
            ),
        }],
    )

    text = response.text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        result = json.loads(text)
        return result.get("new_subdomains", [])
    except json.JSONDecodeError:
        return []


async def run_subdomain_discovery(
    relay: Relay,
    model: str,
    conn: sqlite3.Connection,
    document_ids: list[str] | None = None,
) -> dict:
    """Run subdomain discovery on docs. Returns summary."""
    import uuid
    from .domain_normalizer import normalize_domain_label

    if document_ids is None:
        # Run on all extracted docs
        rows = conn.execute(
            "SELECT id FROM documents WHERE status IN ('extracted', 'enriched')"
        ).fetchall()
        document_ids = [r[0] for r in rows]

    import asyncio

    results = {"docs_checked": 0, "subdomains_added": 0, "new_subdomains": []}

    for doc_id in document_ids:
        if results["docs_checked"] > 0:
            await asyncio.sleep(1)  # Rate limit protection
        new_subs = await discover_subdomains_for_document(relay, model, conn, doc_id)
        results["docs_checked"] += 1

        for sub_path in new_subs:
            # Normalize and create the subdomain
            path = normalize_domain_label(conn, sub_path)

            # Check if already assigned
            existing = conn.execute(
                "SELECT 1 FROM document_domains WHERE document_id = ? AND domain_path = ?",
                (doc_id, path),
            ).fetchone()

            if not existing:
                conn.execute(
                    "INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, ?, 0, 0.6)",
                    (doc_id, path),
                )
                conn.execute(
                    "UPDATE domains SET document_count = document_count + 1 WHERE path = ?",
                    (path,),
                )
                results["subdomains_added"] += 1
                if path not in results["new_subdomains"]:
                    results["new_subdomains"].append(path)

    conn.commit()
    return results
```

- [ ] **Step 4: Run orchestrator tests to check for import issues**

Run: `cd orchestrator && uv run pytest tests/test_classifier.py tests/test_extractor.py -v`
Expected: Tests may fail due to mock patterns — we fix those in Task 9.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/classifier.py orchestrator/src/pipeline/extractor.py orchestrator/src/pipeline/subdomain_discovery.py
git commit -m "refactor(orchestrator): migrate pipeline functions to Relay"
```

---

### Task 7: Migrate orchestrator routes (ingest, reclassify, subdomains)

**Files:**
- Modify: `orchestrator/src/routes/ingest.py:1-250`
- Modify: `orchestrator/src/routes/reclassify.py:1-82`
- Modify: `orchestrator/src/routes/subdomains.py:1-29`

- [ ] **Step 1: Update ingest.py — replace AsyncAnthropicBedrock with Relay**

Change the import at line 7 and client creation at lines 26-30. Replace:

```python
from anthropic import AsyncAnthropicBedrock
```

with:

```python
from orrery_relay import Relay
```

Replace lines 26-30:

```python
    client = AsyncAnthropicBedrock(
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
    )
```

with:

```python
    relay = Relay.from_settings(settings)
```

Then replace every occurrence of `client=client` with `relay=relay` in the function (lines 74, 93, 138). Specifically:

Line 73-76: `classify_document(client=client,` → `classify_document(relay=relay,`
Line 92-94: `extract_document(client=client,` → `extract_document(relay=relay,`
Line 137-140: `extract_document(client=client,` → `extract_document(relay=relay,`

- [ ] **Step 2: Update reclassify.py — replace AsyncAnthropicBedrock with Relay**

Replace the full file with:

```python
# orchestrator/src/routes/reclassify.py
# ABOUTME: Reclassify existing documents with the current classifier prompt.
# ABOUTME: Additive — adds new domains without removing existing ones.

from fastapi import APIRouter
from orrery_relay import Relay
from ..config import get_settings
from ..db import get_connection
from ..pipeline.excerpt import build_classification_excerpt
from ..pipeline.classifier import classify_document
from ..pipeline.domain_normalizer import normalize_domain_label

router = APIRouter()


@router.post("/reclassify")
async def reclassify_all():
    """Re-run classification on all documents. Adds new domains without removing existing ones."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    relay = Relay.from_settings(settings)

    docs = conn.execute("SELECT id, title, content FROM documents ORDER BY created_at").fetchall()
    results = {"docs_processed": 0, "new_domains": [], "new_assignments": 0}

    for doc in docs:
        doc_id, title, content = doc[0], doc[1], doc[2]

        # Get existing assignments
        existing = set(r[0] for r in conn.execute(
            "SELECT domain_path FROM document_domains WHERE document_id = ?", (doc_id,)
        ).fetchall())

        # Get current taxonomy
        taxonomy = [r[0] for r in conn.execute("SELECT path FROM domains ORDER BY path").fetchall()]

        # Classify
        excerpt = build_classification_excerpt(title, content)
        try:
            classification = await classify_document(
                relay=relay, title=title, excerpt=excerpt,
                existing_taxonomy=taxonomy, model=settings.classification_model,
            )
        except Exception as e:
            print(f"  Skip {title}: {e}", flush=True)
            continue

        # Add new domain assignments (don't remove existing)
        all_domains = []
        primary = classification.get("primary_domain")
        if primary:
            all_domains.append(primary)
        for sec in classification.get("secondary_domains", []):
            all_domains.append(sec)

        for domain_path in all_domains:
            if domain_path not in existing:
                path = normalize_domain_label(conn, domain_path)
                conn.execute(
                    "INSERT OR IGNORE INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, ?, 0, 0.7)",
                    (doc_id, path),
                )
                conn.execute(
                    "UPDATE domains SET document_count = document_count + 1 WHERE path = ?", (path,)
                )
                results["new_assignments"] += 1
                if path not in existing and path not in [d for d in results["new_domains"]]:
                    if path not in taxonomy:
                        results["new_domains"].append(path)

        results["docs_processed"] += 1
        print(f"  Reclassified {results['docs_processed']}/{len(docs)}: {title[:40]}", flush=True)

        import asyncio
        await asyncio.sleep(0.5)  # Rate limit

    conn.commit()
    conn.close()
    return results
```

- [ ] **Step 3: Update subdomains.py — replace AsyncAnthropicBedrock with Relay**

Replace the full file with:

```python
# orchestrator/src/routes/subdomains.py
# ABOUTME: Route to trigger subdomain discovery on extracted documents.
# ABOUTME: Uses Relay for LLM calls to the classifier model.

from fastapi import APIRouter
from orrery_relay import Relay
from ..config import get_settings
from ..db import get_connection
from ..pipeline.subdomain_discovery import run_subdomain_discovery

router = APIRouter()


@router.post("/discover-subdomains")
async def trigger_subdomain_discovery():
    """Run subdomain discovery on all extracted docs."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    relay = Relay.from_settings(settings)
    try:
        results = await run_subdomain_discovery(
            relay=relay,
            model=settings.classification_model,
            conn=conn,
        )
    finally:
        conn.close()
    return results
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/routes/ingest.py orchestrator/src/routes/reclassify.py orchestrator/src/routes/subdomains.py
git commit -m "refactor(orchestrator): migrate routes to Relay"
```

---

### Task 8: Migrate search expansion + pipeline

**Files:**
- Modify: `orchestrator/src/pipeline/search/expansion.py:1-49`
- Modify: `orchestrator/src/pipeline/search/pipeline.py:65-92`
- Modify: `orchestrator/src/routes/search.py:1-53`

- [ ] **Step 1: Update expansion.py — use Relay.complete_sync()**

Replace the full file with:

```python
# orchestrator/src/pipeline/search/expansion.py
# ABOUTME: Stage 0: Query expansion via Haiku.
# ABOUTME: Expands a search query into multiple sub-queries using an LLM.

import json
from orrery_relay import Relay


async def expand_query(
    relay: Relay,
    query: str,
    max_sub_queries: int = 5,
) -> list[str]:
    """Expand a query into multiple sub-queries using Haiku."""
    response = await relay.complete(
        model="claude-haiku-4-5",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": f"""Given this search query, generate {max_sub_queries} sub-queries that would help find all relevant information. Include:
- The original query (cleaned up)
- Synonym variations
- Related concepts
- More specific versions of vague terms

Query: {query}

Return as a JSON array of strings only. No explanation.""",
        }],
    )

    text = response.text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        sub_queries = json.loads(text)
        if isinstance(sub_queries, list):
            return sub_queries[:max_sub_queries]
    except json.JSONDecodeError:
        pass

    return [query]
```

- [ ] **Step 2: Update pipeline.py — change search_knowledge_graph signature**

In `orchestrator/src/pipeline/search/pipeline.py`, change the `search_knowledge_graph` function signature (lines 65-72) from:

```python
async def search_knowledge_graph(
    conn: sqlite3.Connection,
    query: str,
    expand: bool = True,
    aws_access_key: str = "",
    aws_secret_key: str = "",
    aws_region: str = "us-east-1",
    top_k: int = 20,
) -> SearchResponse:
```

to:

```python
async def search_knowledge_graph(
    conn: sqlite3.Connection,
    query: str,
    expand: bool = True,
    relay: "Relay | None" = None,
    top_k: int = 20,
) -> SearchResponse:
```

And change lines 84-90 from:

```python
    if expand and aws_access_key:
        from .expansion import expand_query
        sub_queries = await expand_query(
            query, aws_access_key, aws_secret_key, aws_region,
            max_sub_queries=_config.expansion_max_sub_queries,
        )
```

to:

```python
    if expand and relay is not None:
        from .expansion import expand_query
        sub_queries = await expand_query(
            relay, query,
            max_sub_queries=_config.expansion_max_sub_queries,
        )
```

- [ ] **Step 3: Update search.py route — pass relay instead of individual creds**

Replace the full file with:

```python
# orchestrator/src/routes/search.py
# ABOUTME: Search endpoint — full staged pipeline.
# ABOUTME: Searches the knowledge graph with optional query expansion via LLM.

from fastapi import APIRouter
from orrery_relay import Relay
from ..config import get_settings
from ..db import get_connection
from ..pipeline.search import search_knowledge_graph, build_indexes, embed_new_entities, embed_new_chunks
from ..broadcast import broadcast_search

router = APIRouter()


@router.get("/search")
async def search_query(q: str, top_k: int = 20, expand: bool = True):
    """Search the knowledge graph. Broadcasts results to viz clients."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    relay = Relay.from_settings(settings)

    response = await search_knowledge_graph(
        conn, q,
        expand=expand,
        relay=relay,
        top_k=top_k,
    )
    conn.close()

    # Broadcast to viz
    entity_names = [e["name"] for e in response.entities[:10] if e.get("name")]
    if entity_names:
        await broadcast_search(q, entity_names)

    return {
        "query": response.query,
        "entities": response.entities,
        "chunks": response.chunks,
        "sub_queries_used": response.sub_queries_used,
        "total_entities": response.total_entities,
        "total_chunks": response.total_chunks,
    }


@router.post("/search/rebuild")
def rebuild_search_index():
    """Rebuild FAISS indexes and embed any unembedded entities/chunks."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    new_entities = embed_new_entities(conn)
    new_chunks = embed_new_chunks(conn)
    stats = build_indexes(conn)
    conn.close()
    return {"status": "rebuilt", "new_entities_embedded": new_entities, "new_chunks_embedded": new_chunks, **stats}
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/pipeline/search/expansion.py orchestrator/src/pipeline/search/pipeline.py orchestrator/src/routes/search.py
git commit -m "refactor(orchestrator): migrate search pipeline to Relay"
```

---

### Task 9: Migrate worker files

**Files:**
- Modify: `worker/src/config.py:1-36`
- Modify: `worker/pyproject.toml:1-28`
- Modify: `worker/src/jobs/extract_batch.py:1-139`
- Modify: `worker/src/jobs/simmer_general.py:1-223`
- Modify: `worker/src/jobs/simmer_domain.py:1-159`

- [ ] **Step 1: Update worker/src/config.py (identical changes to orchestrator)**

Replace the full file with the same content as orchestrator's config.py (Task 5 Step 1). The files are identical.

- [ ] **Step 2: Add orrery-relay dependency to worker/pyproject.toml**

Add to the `dependencies` list:

```
    "orrery-relay",
```

And add a `[tool.uv.sources]` section:

```toml
[tool.uv.sources]
orrery-relay = { path = "../packages/orrery-relay" }
```

- [ ] **Step 3: Update extract_batch.py — replace AsyncAnthropicBedrock with Relay**

Change line 4 from:

```python
from anthropic import AsyncAnthropicBedrock
```

to:

```python
from orrery_relay import Relay
```

Replace lines 11-15:

```python
    client = AsyncAnthropicBedrock(
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
    )
```

with:

```python
    relay = Relay.from_settings(settings)
```

Replace lines 55-58 (the `client.messages.create` call):

```python
            response = await client.messages.create(
                model=settings.extraction_model, max_tokens=4096,
                messages=[{"role": "user", "content": f"{spec}\n\nTEXT:\n{chunk_text}\n\nRespond with JSON only: {{\"entities\": [{{\"name\": \"...\", \"type\": \"...\"}}]}}"}],
            )
            text = response.content[0].text
```

with:

```python
            response = await relay.complete(
                model=settings.extraction_model, max_tokens=4096,
                messages=[{"role": "user", "content": f"{spec}\n\nTEXT:\n{chunk_text}\n\nRespond with JSON only: {{\"entities\": [{{\"name\": \"...\", \"type\": \"...\"}}]}}"}],
            )
            text = response.text
```

Also change the markdown-fence stripping that follows — `response.text` already gives us the text, so remove:

```python
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
```

Wait — keep the fence stripping. `response.text` is the raw text content from the model which may include markdown fences. The stripping is about the LLM output format, not the SDK.

- [ ] **Step 4: Update simmer_general.py — replace AsyncAnthropicBedrock in _parse_judgment_file**

In `_parse_judgment_file` (lines 26-68), replace lines 27-34:

```python
    """Use Haiku to extract per-criterion details from a judgment file."""
    from anthropic import AsyncAnthropicBedrock

    client = AsyncAnthropicBedrock(
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
    )
```

with:

```python
    """Use Haiku to extract per-criterion details from a judgment file."""
    from orrery_relay import Relay

    relay = Relay.from_settings(settings)
```

Replace lines 57-61:

```python
        response = await client.messages.create(
            model=settings.extraction_model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
```

with:

```python
        response = await relay.complete(
            model=settings.extraction_model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.text
```

- [ ] **Step 5: Update simmer_domain.py — replace bedrock_kwargs**

In `simmer_domain.py`, replace lines 71-76:

```python
    bedrock_kwargs = {
        "api_provider": "bedrock",
        "aws_access_key": settings.aws_access_key,
        "aws_secret_key": settings.aws_secret_key,
        "aws_region": settings.aws_region,
    }
```

with:

```python
    # NOTE: simmer-sdk still uses bedrock_kwargs until it's migrated to accept a Relay.
    # Once simmer-sdk is updated, this will become: relay=Relay.from_settings(settings)
    bedrock_kwargs = {
        "api_provider": "bedrock",
        "aws_access_key": settings.aws_access_key,
        "aws_secret_key": settings.aws_secret_key,
        "aws_region": settings.aws_region,
    }
```

Do the same for `simmer_general.py` lines 150-155 — keep the `bedrock_kwargs` dict as-is since `refine()` still expects it until simmer-sdk is updated.

- [ ] **Step 6: Run `uv sync` in worker**

Run: `cd worker && uv sync --dev`
Expected: resolves without error

- [ ] **Step 7: Commit**

```bash
git add worker/src/config.py worker/pyproject.toml worker/src/jobs/extract_batch.py worker/src/jobs/simmer_general.py worker/src/jobs/simmer_domain.py
git commit -m "refactor(worker): migrate to Relay for direct API calls"
```

---

### Task 10: Update existing tests

**Files:**
- Modify: `orchestrator/tests/test_classifier.py:1-29`
- Modify: `orchestrator/tests/test_extractor.py:1-29`
- Modify: `orchestrator/tests/test_ingest_route.py:1-214`

- [ ] **Step 1: Update test_classifier.py — mock Relay instead of client**

Replace the full file:

```python
# orchestrator/tests/test_classifier.py
# ABOUTME: Tests for the document classifier pipeline function.
# ABOUTME: Verifies classification returns correct domain structure.

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.classifier import classify_document


@pytest.mark.asyncio
async def test_classify_returns_domains():
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "primary_domain": "techniques/wet-blending",
        "secondary_domains": ["theory/color-theory"],
        "new_domains": [],
        "confidence": 0.9,
    })

    mock_relay = AsyncMock()
    mock_relay.complete = AsyncMock(return_value=mock_response)

    result = await classify_document(
        relay=mock_relay,
        title="Wet Blending Tutorial",
        excerpt="How to wet blend on miniatures...",
        existing_taxonomy=["techniques", "theory"],
        model="claude-sonnet-4-6",
    )

    assert result["primary_domain"] == "techniques/wet-blending"
    assert "theory/color-theory" in result["secondary_domains"]
    mock_relay.complete.assert_called_once()
```

- [ ] **Step 2: Update test_extractor.py — mock Relay instead of client**

Replace the full file:

```python
# orchestrator/tests/test_extractor.py
# ABOUTME: Tests for the entity extractor pipeline function.
# ABOUTME: Verifies extraction returns correct entity structure.

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.extractor import extract_entities_from_chunk


@pytest.mark.asyncio
async def test_extract_entities_returns_list():
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "entities": [
            {"name": "wet blending", "type": "Technique"},
            {"name": "Duncan Rhodes", "type": "Person"},
        ]
    })

    mock_relay = AsyncMock()
    mock_relay.complete = AsyncMock(return_value=mock_response)

    entities = await extract_entities_from_chunk(
        relay=mock_relay,
        chunk_text="Duncan Rhodes demonstrates wet blending...",
        spec="Extract entities: Person, Technique, Thing from this text.",
        model="claude-haiku-4-5",
    )

    assert len(entities) == 2
    assert entities[0]["name"] == "wet blending"
    assert entities[0]["type"] == "Technique"
```

- [ ] **Step 3: Update test_ingest_route.py — fix Settings construction and mocks**

The test helper `make_test_settings` uses fields that don't exist on the current Settings class. Update it and all patches. Replace the full file:

```python
# orchestrator/tests/test_ingest_route.py
# ABOUTME: Tests for the /ingest route and document ingestion pipeline.
# ABOUTME: Verifies document storage, classification, extraction, and job queueing.

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from src.db import init_db
from src.config import Settings


MOCK_CLASSIFICATION = {
    "primary_domain": "techniques/wet-blending",
    "secondary_domains": [],
    "new_domains": [],
    "confidence": 0.9,
}


def make_test_settings(tmp_path):
    return Settings(
        anthropic_backend="gateway",
        gateway_url="https://test.gateway",
        gateway_api_key="test-key",
        db_path=str(tmp_path / "test.db"),
        documents_dir=str(tmp_path / "documents"),
    )


@pytest.fixture
def client(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        with TestClient(app) as c:
            yield c


@pytest.fixture
def client_with_mocked_classify(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION):
        from src.main import app
        with TestClient(app) as c:
            yield c, settings


@pytest.mark.asyncio
async def test_ingest_stores_document(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("Test Doc", "Hello world content", None)

    assert "document_id" in result
    assert result["title"] == "Test Doc"

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (result["document_id"],)).fetchone()
    assert row is not None
    assert row["title"] == "Test Doc"
    assert row["content"] == "Hello world content"
    conn.close()


@pytest.mark.asyncio
async def test_ingest_creates_chunks(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    long_content = "word " * 1000

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("Chunky Doc", long_content, None)

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    chunks = conn.execute(
        "SELECT * FROM chunks WHERE document_id = ?", (result["document_id"],)
    ).fetchall()
    assert len(chunks) > 1
    conn.close()


@pytest.mark.asyncio
async def test_ingest_assigns_classification(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("Classified Doc", "Some content about painting", None)

    assert "techniques/wet-blending" in result["domains"]

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    domain_rows = conn.execute(
        "SELECT domain_path FROM document_domains WHERE document_id = ?", (result["document_id"],)
    ).fetchall()
    domain_paths = [r["domain_path"] for r in domain_rows]
    assert "techniques/wet-blending" in domain_paths
    conn.close()


@pytest.mark.asyncio
async def test_ingest_queues_simmer_general_job_when_no_spec(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("No Spec Doc", "Some content", None)

    assert len(result["jobs_queued"]) > 0

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    job = conn.execute(
        "SELECT * FROM jobs WHERE type = 'simmer_general' AND status = 'queued'"
    ).fetchone()
    assert job is not None
    assert job["id"] in result["jobs_queued"]
    conn.close()


@pytest.mark.asyncio
async def test_ingest_does_not_duplicate_simmer_general_job(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result1 = await _ingest_document("Doc 1", "Content 1", None)
        result2 = await _ingest_document("Doc 2", "Content 2", None)

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    jobs = conn.execute(
        "SELECT * FROM jobs WHERE type = 'simmer_general'"
    ).fetchall()
    assert len(jobs) == 1
    conn.close()


@pytest.mark.asyncio
async def test_ingest_skips_extraction_when_no_spec(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("No Extract Doc", "Content without spec", None)

    assert result["entity_count"] == 0


@pytest.mark.asyncio
async def test_ingest_extracts_entities_when_spec_exists(tmp_path):
    settings = make_test_settings(tmp_path)
    init_db(settings.db_path)

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    import uuid
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, ?)",
        (str(uuid.uuid4()), "Extract: names and places"),
    )
    conn.commit()
    conn.close()

    mock_entities = [
        {"name": "Citadel", "type": "Brand"},
        {"name": "Abaddon Black", "type": "Paint"},
    ]

    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.extract_document", new_callable=AsyncMock, return_value=mock_entities), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        result = await _ingest_document("Extract Doc", "Content with entities", None)

    assert result["entity_count"] == 2

    from src.db import get_connection
    conn = get_connection(settings.db_path)
    entities = conn.execute("SELECT * FROM entities").fetchall()
    assert len(entities) == 2
    conn.close()
```

- [ ] **Step 4: Run all orchestrator tests**

Run: `cd orchestrator && uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Run worker tests**

Run: `cd worker && uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add orchestrator/tests/ worker/tests/
git commit -m "test: update mocks from client.messages.create to relay.complete"
```

---

### Task 11: Run full verification

**Files:** None (verification only)

- [ ] **Step 1: Run orrery-relay test suite**

Run: `cd packages/orrery-relay && uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Run orchestrator test suite**

Run: `cd orchestrator && uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Run worker test suite**

Run: `cd worker && uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Verify no remaining Anthropic client imports in orchestrator/worker source**

Run: `grep -rn "from anthropic import" orchestrator/src/ worker/src/`
Expected: No results. All Anthropic imports should now be inside `packages/orrery-relay/`.

- [ ] **Step 5: Commit any remaining fixes**

If any test failures were found and fixed, commit them.

---

### Task 12: Update CLAUDE.md with orrery-relay documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add orrery-relay section to CLAUDE.md**

Add the following after the "### All Claude API Calls Go Through Bedrock" section (which should be updated). Replace that section with:

```markdown
### All Claude API Calls Go Through orrery-relay

Never instantiate Anthropic clients directly. Always use the `Relay` class from `orrery-relay`:

```python
from orrery_relay import Relay

relay = Relay.from_settings(settings)
response = await relay.complete(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "..."}],
    max_tokens=1024,
)
text = response.text
```

The relay supports two backends controlled by `ANTHROPIC_BACKEND` env var:
- `gateway` (default): Routes through the Bedrock Gateway proxy at the configured `GATEWAY_URL`
- `bedrock`: Direct AWS Bedrock access with `AWS_ACCESS_KEY`/`AWS_SECRET_KEY`

Always use friendly model names (`claude-sonnet-4-6`, `claude-haiku-4-5`). The relay translates to Bedrock IDs when needed.

The `orrery-relay` package lives at `packages/orrery-relay/` and is a dependency of both orchestrator and worker via `[tool.uv.sources]` path reference.
```

- [ ] **Step 2: Update the Model ID Format section**

Replace the "### Model ID Format for Bedrock" section with:

```markdown
### Model Names

Use friendly model names everywhere in config and code:
```
claude-sonnet-4-6
claude-haiku-4-5
claude-opus-4-6
```

The relay handles translation to Bedrock inference profile IDs (`us.anthropic.claude-sonnet-4-20250514-v1:0`, etc.) when running in bedrock mode. Check `packages/orrery-relay/src/orrery_relay/backends.py` for the current mapping.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for orrery-relay"
```
