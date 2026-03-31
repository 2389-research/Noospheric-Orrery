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
