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
