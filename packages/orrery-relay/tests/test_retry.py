# ABOUTME: Tests for exponential backoff retry logic.
# ABOUTME: Verifies retry on transient errors, no retry on permanent errors.

import pytest
from unittest.mock import MagicMock
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
