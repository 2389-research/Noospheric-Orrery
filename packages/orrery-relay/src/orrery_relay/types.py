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
    # Prompt-caching usage (Anthropic/Bedrock only; 0 on ollama). cache_read is
    # billed at ~0.1x input, cache_creation at ~1.25x — a caller that marks a
    # cache breakpoint needs these to confirm the block is actually being reused
    # rather than silently re-billed at full price on every call.
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


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
