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


# --- Retry-After parsing -----------------------------------------------------
# Every value here reaches `time.sleep` via _compute_delay, so a bad one does not
# degrade the retry — it breaks the thing meant to recover from the failure.

import math

import pytest

from orrery_relay.retry import _MAX_RETRY_AFTER, _compute_delay, _parse_retry_after


@pytest.mark.parametrize("header", ["-1", "-0.5", "nan", "inf", "-inf", "Infinity"])
def test_a_hostile_numeric_retry_after_falls_back_to_backoff(header):
    """`float()` accepts all of these; sleep does not.

    Negative and nan make `time.sleep` raise ValueError — aborting the retry that was
    supposed to recover — and inf sleeps forever, which is a silently hung worker rather
    than an error anyone can see. None means "use computed backoff".
    """
    assert _parse_retry_after(header) is None


@pytest.mark.parametrize("header", ["", None, "soon", "12 seconds", "not-a-date"])
def test_an_unparseable_retry_after_falls_back_to_backoff(header):
    assert _parse_retry_after(header) is None


def test_a_valid_delta_seconds_header_is_honoured():
    assert _parse_retry_after("120") == 120.0
    assert _parse_retry_after("0") == 0.0


def test_an_absurdly_large_retry_after_is_capped():
    """Honouring the server is the point, but not without bound.

    Capped rather than clamped to max_delay: a server saying 120s means it, and
    retrying at 30s would just earn another 429. The cap only stops one header from
    stalling a job indefinitely.
    """
    assert _parse_retry_after("999999") == _MAX_RETRY_AFTER


def test_an_http_date_in_the_past_means_retry_now_not_negative():
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


def test_every_parsed_value_is_safe_to_sleep_on():
    """The property that actually matters, asserted through the caller.

    _compute_delay returns retry_after unchanged, so whatever survives parsing is passed
    straight to sleep.
    """
    for header in ["-1", "nan", "inf", "999999", "120", "0", "garbage", ""]:
        delay = _compute_delay(1, 1.0, 30.0, _parse_retry_after(header))
        assert math.isfinite(delay) and delay >= 0, f"{header!r} -> unsleepable {delay!r}"
