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
        gateway_url: str = "",
        gateway_api_key: str = "",
        aws_access_key: str = "",
        aws_secret_key: str = "",
        aws_region: str = "us-east-1",
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
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
            backend=backend, gateway_url=gateway_url, gateway_api_key=gateway_api_key,
            aws_access_key=aws_access_key, aws_secret_key=aws_secret_key, aws_region=aws_region,
        )
        self._sync_client: Any = None

    @classmethod
    def from_env(cls, **overrides: Any) -> Relay:
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
        self, model: str, messages: list[dict], max_tokens: int,
        system: str | None = None, temperature: float | None = None,
        tools: list[dict] | None = None, tool_choice: dict | None = None,
        **kwargs: Any,
    ) -> RelayResponse:
        mapped_model = map_model_id(model, self._backend)
        call_kwargs: dict[str, Any] = {"model": mapped_model, "messages": messages, "max_tokens": max_tokens}
        if system is not None: call_kwargs["system"] = system
        if temperature is not None: call_kwargs["temperature"] = temperature
        if tools is not None: call_kwargs["tools"] = tools
        if tool_choice is not None: call_kwargs["tool_choice"] = tool_choice
        call_kwargs.update(kwargs)

        start = time.monotonic()
        async def _call() -> Any:
            return await self._async_client.messages.create(**call_kwargs)

        try:
            raw = await with_retry(_call, max_retries=self._max_retries, base_delay=self._base_delay, max_delay=self._max_delay)
        except Exception:
            elapsed = (time.monotonic() - start) * 1000
            logger.error("failed model=%s status=error latency=%.0fms", model, elapsed)
            raise

        elapsed = (time.monotonic() - start) * 1000
        text = raw.content[0].text if raw.content else ""
        input_tokens = raw.usage.input_tokens
        output_tokens = raw.usage.output_tokens

        logger.info("complete model=%s backend=%s tokens=%d/%d latency=%.0fms", model, self._backend, input_tokens, output_tokens, elapsed)

        response = RelayResponse(raw=raw, text=text, input_tokens=input_tokens, output_tokens=output_tokens, model=model, latency_ms=elapsed, backend=self._backend)

        if self._on_usage:
            from datetime import datetime, timezone
            event = UsageEvent(model=model, backend=self._backend, input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=elapsed, timestamp=datetime.now(timezone.utc).isoformat(), retries=0)
            await self._on_usage(event)

        return response

    def complete_sync(
        self, model: str, messages: list[dict], max_tokens: int,
        system: str | None = None, temperature: float | None = None,
        **kwargs: Any,
    ) -> RelayResponse:
        if self._sync_client is None:
            self._sync_client = create_sync_client(
                backend=self._backend, gateway_url=self._gateway_url, gateway_api_key=self._gateway_api_key,
                aws_access_key=self._aws_access_key, aws_secret_key=self._aws_secret_key, aws_region=self._aws_region,
            )
        mapped_model = map_model_id(model, self._backend)
        call_kwargs: dict[str, Any] = {"model": mapped_model, "messages": messages, "max_tokens": max_tokens}
        if system is not None: call_kwargs["system"] = system
        if temperature is not None: call_kwargs["temperature"] = temperature
        call_kwargs.update(kwargs)

        start = time.monotonic()
        def _call() -> Any:
            return self._sync_client.messages.create(**call_kwargs)
        raw = with_retry_sync(_call, max_retries=self._max_retries, base_delay=self._base_delay, max_delay=self._max_delay)

        elapsed = (time.monotonic() - start) * 1000
        text = raw.content[0].text if raw.content else ""
        logger.info("complete_sync model=%s backend=%s tokens=%d/%d latency=%.0fms", model, self._backend, raw.usage.input_tokens, raw.usage.output_tokens, elapsed)
        return RelayResponse(raw=raw, text=text, input_tokens=raw.usage.input_tokens, output_tokens=raw.usage.output_tokens, model=model, latency_ms=elapsed, backend=self._backend)
