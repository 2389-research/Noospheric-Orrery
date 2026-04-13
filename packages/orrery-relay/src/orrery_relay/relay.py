# ABOUTME: The Relay class — main interface for orrery-relay.
# ABOUTME: Wraps client creation, model mapping, retry, logging, and usage tracking.

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .backends import create_async_client, create_sync_client, map_model_id
from .retry import with_retry, with_retry_sync
from .types import RelayResponse, UsageEvent

logger = logging.getLogger("orrery_relay")


def _anthropic_to_ollama_messages(messages: list[dict], system: str | None = None) -> tuple[list[dict], str | None]:
    """Translate Anthropic message format to native Ollama /api/chat format.

    Extracts images from content blocks into the 'images' array.
    Returns (ollama_messages, system_prompt).
    """
    result = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            result.append({"role": msg["role"], "content": content})
        elif isinstance(content, list):
            text_parts = []
            images = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "image":
                        source = block.get("source", {})
                        if source.get("type") == "base64":
                            images.append(source.get("data", ""))
                    elif block.get("type") == "text":
                        text_parts.append(block["text"])
            entry = {"role": msg["role"], "content": "\n".join(text_parts)}
            if images:
                entry["images"] = images
            result.append(entry)
        else:
            result.append({"role": msg["role"], "content": str(content) if content else ""})
    return result, system


def _parse_json_from_text(text: str) -> dict | None:
    """Try to extract a JSON object from text that may have markdown fences."""
    text = text.strip()
    if "```" in text:
        match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


class Relay:
    """Shared LLM client that supports Bedrock, Gateway, and Ollama backends."""

    def __init__(
        self,
        backend: str = "gateway",
        gateway_url: str = "",
        gateway_api_key: str = "",
        aws_access_key: str = "",
        aws_secret_key: str = "",
        aws_region: str = "us-east-1",
        ollama_url: str = "http://localhost:11434",
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        on_usage: Callable[[UsageEvent], Awaitable[None]] | None = None,
    ) -> None:
        self._backend = backend
        self._ollama_url = ollama_url
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._on_usage = on_usage

        if backend != "ollama":
            self._async_client = create_async_client(
                backend=backend, gateway_url=gateway_url, gateway_api_key=gateway_api_key,
                aws_access_key=aws_access_key, aws_secret_key=aws_secret_key, aws_region=aws_region,
                ollama_url=ollama_url,
            )

        # Store for sync client creation
        self._gateway_url = gateway_url
        self._gateway_api_key = gateway_api_key
        self._aws_access_key = aws_access_key
        self._aws_secret_key = aws_secret_key
        self._aws_region = aws_region
        self._sync_client: Any = None

    @classmethod
    def from_env(cls, **overrides: Any) -> Relay:
        log_level = os.environ.get("RELAY_LOG_LEVEL", "INFO")
        logging.getLogger("orrery_relay").setLevel(getattr(logging, log_level.upper(), logging.INFO))
        explicit_backend = os.environ.get("ANTHROPIC_BACKEND", "")
        aws_key = os.environ.get("AWS_ACCESS_KEY", "")
        gateway_url = os.environ.get("GATEWAY_URL", "")
        ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        has_explicit_ollama_url = "OLLAMA_URL" in os.environ
        if explicit_backend:
            backend = explicit_backend
        elif aws_key:
            backend = "bedrock"
        elif gateway_url:
            backend = "gateway"
        elif has_explicit_ollama_url:
            backend = "ollama"
        else:
            backend = "gateway"
        kwargs: dict[str, Any] = {
            "backend": backend,
            "gateway_url": gateway_url,
            "gateway_api_key": os.environ.get("GATEWAY_API_KEY", ""),
            "aws_access_key": aws_key,
            "aws_secret_key": os.environ.get("AWS_SECRET_KEY", ""),
            "aws_region": os.environ.get("AWS_REGION", "us-east-1"),
            "ollama_url": ollama_url,
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
            "ollama_url": getattr(settings, "ollama_url", "http://localhost:11434"),
        }
        kwargs.update(overrides)
        return cls(**kwargs)

    async def _complete_ollama(
        self, model: str, messages: list[dict], max_tokens: int,
        system: str | None = None, temperature: float | None = None,
        **kwargs: Any,
    ) -> RelayResponse:
        """Ollama completion via native /api/chat endpoint.

        Uses the native endpoint instead of the OpenAI-compatible one because:
        - Vision (image content blocks) works correctly
        - No thinking mode issues (gemma4 ThinkingBlock bug)
        - Consistent behavior across all Ollama model families
        """
        import httpx

        ollama_messages, _ = _anthropic_to_ollama_messages(messages, system)
        if system:
            ollama_messages.insert(0, {"role": "system", "content": system})

        # Check if any message has images — num_predict option breaks vision on gemma4
        has_images = any("images" in m for m in ollama_messages)

        body: dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,
        }
        if not has_images:
            body["options"] = {"num_predict": max_tokens}
        if temperature is not None:
            body.setdefault("options", {})["temperature"] = temperature

        start = time.monotonic()

        async def _call() -> Any:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(f"{self._ollama_url}/api/chat", json=body)
                resp.raise_for_status()
                return resp.json()

        data = await with_retry(_call, max_retries=self._max_retries, base_delay=self._base_delay, max_delay=self._max_delay)
        elapsed = (time.monotonic() - start) * 1000

        text = data.get("message", {}).get("content", "")
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        logger.info("complete model=%s backend=ollama tokens=%d/%d latency=%.0fms", model, input_tokens, output_tokens, elapsed)

        response = RelayResponse(raw=data, text=text, input_tokens=input_tokens, output_tokens=output_tokens, model=model, latency_ms=elapsed, backend="ollama")

        if self._on_usage:
            from datetime import datetime, timezone
            event = UsageEvent(model=model, backend="ollama", input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=elapsed, timestamp=datetime.now(timezone.utc).isoformat(), retries=0)
            await self._on_usage(event)

        return response

    async def complete(
        self, model: str, messages: list[dict], max_tokens: int,
        system: str | None = None, temperature: float | None = None,
        tools: list[dict] | None = None, tool_choice: dict | None = None,
        **kwargs: Any,
    ) -> RelayResponse:
        if self._backend == "ollama":
            return await self._complete_ollama(model, messages, max_tokens, system, temperature, **kwargs)

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
        text = ""
        if raw.content:
            text_parts = [block.text for block in raw.content if hasattr(block, "text")]
            text = "\n".join(text_parts)
        input_tokens = raw.usage.input_tokens
        output_tokens = raw.usage.output_tokens

        logger.info("complete model=%s backend=%s tokens=%d/%d latency=%.0fms", model, self._backend, input_tokens, output_tokens, elapsed)

        response = RelayResponse(raw=raw, text=text, input_tokens=input_tokens, output_tokens=output_tokens, model=model, latency_ms=elapsed, backend=self._backend)

        if self._on_usage:
            from datetime import datetime, timezone
            event = UsageEvent(model=model, backend=self._backend, input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=elapsed, timestamp=datetime.now(timezone.utc).isoformat(), retries=0)
            await self._on_usage(event)

        return response

    async def complete_structured(
        self, model: str, messages: list[dict], max_tokens: int,
        schema: dict, tool_name: str = "structured_output",
        tool_description: str = "Return structured data",
        system: str | None = None, temperature: float | None = None,
        **kwargs: Any,
    ) -> dict:
        """LLM call that returns JSON matching a schema.

        For Anthropic/Bedrock: uses tool_use to force structured output.
        For Ollama: prompts for JSON and parses from text response.
        """
        if self._backend == "ollama":
            schema_hint = json.dumps(schema, indent=2)
            json_instruction = f"\n\nReturn your response as a JSON object matching this schema:\n{schema_hint}\n\nReturn ONLY the JSON object, no other text."

            augmented = list(messages)
            if augmented and augmented[-1]["role"] == "user":
                content = augmented[-1]["content"]
                if isinstance(content, str):
                    augmented[-1] = {**augmented[-1], "content": content + json_instruction}
                elif isinstance(content, list):
                    augmented[-1] = {**augmented[-1], "content": content + [{"type": "text", "text": json_instruction}]}

            response = await self._complete_ollama(model, augmented, max_tokens, system, temperature, **kwargs)
            parsed = _parse_json_from_text(response.text)
            return parsed if parsed is not None else {}

        # Anthropic/Bedrock: use tool_use
        tools = [{
            "name": tool_name,
            "description": tool_description,
            "input_schema": schema,
        }]
        tool_choice = {"type": "tool", "name": tool_name}

        response = await self.complete(
            model=model, messages=messages, max_tokens=max_tokens,
            system=system, temperature=temperature,
            tools=tools, tool_choice=tool_choice,
            **kwargs,
        )

        for block in response.raw.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input

        return {}

    def complete_sync(
        self, model: str, messages: list[dict], max_tokens: int,
        system: str | None = None, temperature: float | None = None,
        **kwargs: Any,
    ) -> RelayResponse:
        if self._sync_client is None:
            self._sync_client = create_sync_client(
                backend=self._backend, gateway_url=self._gateway_url, gateway_api_key=self._gateway_api_key,
                aws_access_key=self._aws_access_key, aws_secret_key=self._aws_secret_key, aws_region=self._aws_region,
                ollama_url=self._ollama_url,
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
        text = "\n".join(b.text for b in raw.content if hasattr(b, "text")) if raw.content else ""
        logger.info("complete_sync model=%s backend=%s tokens=%d/%d latency=%.0fms", model, self._backend, raw.usage.input_tokens, raw.usage.output_tokens, elapsed)
        return RelayResponse(raw=raw, text=text, input_tokens=raw.usage.input_tokens, output_tokens=raw.usage.output_tokens, model=model, latency_ms=elapsed, backend=self._backend)
