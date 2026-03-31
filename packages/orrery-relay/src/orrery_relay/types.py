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
