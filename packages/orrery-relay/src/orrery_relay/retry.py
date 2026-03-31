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
                attempt + 1, max_retries, e.response.status_code, delay,
            )
            await asyncio.sleep(delay)
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
                attempt + 1, max_retries, e.response.status_code, delay,
            )
            time.sleep(delay)
    raise last_error  # type: ignore[misc]
