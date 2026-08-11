# ABOUTME: Exponential backoff with jitter for transient API errors.
# ABOUTME: Retries on 429/500/502/503/529; raises immediately on 400/401/404.

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable, TypeVar

import httpx
from anthropic import APIStatusError

logger = logging.getLogger("orrery_relay")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

# Transient failures reach this module two ways: the Anthropic SDK (bedrock /
# gateway) raises APIStatusError, while the raw httpx backends (ollama, gengen)
# raise httpx.HTTPStatusError from resp.raise_for_status(). Both expose
# .response.status_code and .response.headers, so one handler covers both — with
# only APIStatusError caught, a 429/5xx from the httpx backends bypassed retry
# entirely and max_retries did nothing.
_RETRYABLE_EXC = (APIStatusError, httpx.HTTPStatusError)

T = TypeVar("T")


def _parse_retry_after(header: str | None) -> float | None:
    """Parse a Retry-After header into a delay in seconds.

    RFC 7231 allows either delta-seconds ("120") or an HTTP-date
    ("Wed, 21 Oct 2026 07:28:00 GMT"). Returns None on an absent or unparseable
    value so the caller falls back to computed backoff — a malformed header must
    never crash the retry loop (the old float(header) raised ValueError on dates).
    """
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


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
        except _RETRYABLE_EXC as e:
            if e.response.status_code not in RETRYABLE_STATUS_CODES:
                raise
            last_error = e
            if attempt == max_retries:
                raise
            retry_after = _parse_retry_after(e.response.headers.get("retry-after"))
            delay = _compute_delay(attempt, base_delay, max_delay, retry_after)
            logger.warning(
                "retry attempt=%d/%d status=%d delay=%.1fs",
                attempt + 1, max_retries, e.response.status_code, delay,
            )
            await asyncio.sleep(delay)
        except httpx.TransportError as e:
            # Connect/read/write timeouts and connection resets. A separate branch
            # because a TransportError has no `.response`, so it cannot be filtered by
            # status — there is no status. Retried unconditionally: these are transient
            # by definition, and the local backends are where they actually show up (an
            # Ollama busy loading a model refuses connections for a few seconds).
            last_error = e
            if attempt == max_retries:
                raise
            delay = _compute_delay(attempt, base_delay, max_delay, None)
            logger.warning("retry attempt=%d/%d transport=%s delay=%.1fs",
                           attempt + 1, max_retries, type(e).__name__, delay)
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
        except _RETRYABLE_EXC as e:
            if e.response.status_code not in RETRYABLE_STATUS_CODES:
                raise
            last_error = e
            if attempt == max_retries:
                raise
            retry_after = _parse_retry_after(e.response.headers.get("retry-after"))
            delay = _compute_delay(attempt, base_delay, max_delay, retry_after)
            logger.warning(
                "retry attempt=%d/%d status=%d delay=%.1fs",
                attempt + 1, max_retries, e.response.status_code, delay,
            )
            time.sleep(delay)
        except httpx.TransportError as e:
            # See with_retry: no `.response`, so no status filter; transient by nature.
            # This path is the one orrery-codesum uses for every file summary, so an
            # Ollama hiccup mid-traversal used to abort the whole repo ingest.
            last_error = e
            if attempt == max_retries:
                raise
            delay = _compute_delay(attempt, base_delay, max_delay, None)
            logger.warning("retry attempt=%d/%d transport=%s delay=%.1fs",
                           attempt + 1, max_retries, type(e).__name__, delay)
            time.sleep(delay)
    raise last_error  # type: ignore[misc]
