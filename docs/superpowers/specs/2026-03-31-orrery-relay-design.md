# orrery-relay: Shared LLM Client SDK

**Date:** 2026-03-31
**Status:** Draft
**Scope:** New package in `/packages/orrery-relay/`

## Problem

The Noospheric Orrery (orchestrator + worker) and simmer-sdk each instantiate Anthropic clients directly, tightly coupling them to AWS Bedrock credentials and Bedrock-format model IDs. Adding the Bedrock Gateway proxy as an alternative backend means touching 6+ instantiation sites across two services plus 8 internal client creation points in simmer-sdk.

We need a shared abstraction that both the Orrery and simmer-sdk can consume, providing:
- Dual-backend support (direct Bedrock and Bedrock Gateway proxy)
- Model ID normalization (friendly names everywhere, translation handled internally)
- Retry logic, structured logging, and usage tracking

## Decision

Create `orrery-relay`, a Python package in the Orrery monorepo at `/packages/orrery-relay/`. Both services and simmer-sdk depend on it.

## Architecture

### Package location

```
packages/
  orrery-relay/
    pyproject.toml
    src/
      orrery_relay/
        __init__.py        — exports Relay, RelayResponse, UsageEvent
        relay.py           — Relay class (complete, complete_sync, from_env, from_settings)
        backends.py        — client factory, model ID mapping
        retry.py           — exponential backoff with jitter
        types.py           — RelayResponse, UsageEvent, BackendConfig
    tests/
      test_relay.py
      test_backends.py
      test_retry.py
```

**Dependencies:** `anthropic` (already required by both services). No new external dependencies.

### Core interface

```python
from orrery_relay import Relay

# From environment variables
relay = Relay.from_env()

# From an Orrery Settings dataclass
relay = Relay.from_settings(settings)

# Explicit construction
relay = Relay(
    backend="gateway",
    gateway_url="https://bedrock-gateway.2389-research-inc.workers.dev",
    gateway_api_key="...",
    max_retries=3,
    on_usage=my_callback,
)

# Async completion
response = await relay.complete(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=1024,
)

print(response.text)           # first text content block
print(response.input_tokens)   # from usage
print(response.output_tokens)  # from usage
print(response.raw)            # the original anthropic.types.Message

# Sync completion (for the one call site that needs it)
response = relay.complete_sync(
    model="claude-haiku-4-5",
    messages=[...],
    max_tokens=512,
)
```

### Backend selection

A single environment variable controls which backend both services use:

```
ANTHROPIC_BACKEND=gateway   # or "bedrock"
```

**Gateway mode:**

```
GATEWAY_URL=https://bedrock-gateway.2389-research-inc.workers.dev
GATEWAY_API_KEY=<token>
```

- Creates `AsyncAnthropic(api_key=..., base_url=...)` (or sync `Anthropic` for `complete_sync`)
- Model IDs pass through unchanged — the gateway accepts friendly names like `claude-sonnet-4-6`

**Bedrock mode:**

```
AWS_ACCESS_KEY=<key>
AWS_SECRET_KEY=<secret>
AWS_REGION=us-east-1
```

- Creates `AsyncAnthropicBedrock(aws_access_key=..., aws_secret_key=..., aws_region=...)` (or sync `AnthropicBedrock`)
- Model IDs are translated from friendly names to Bedrock inference profile IDs:

```python
BEDROCK_MODEL_MAP = {
    "claude-sonnet-4-6":    "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "claude-sonnet-4-5":    "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "claude-haiku-4-5":     "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-opus-4-6":      "us.anthropic.claude-opus-4-6-v1:0",
}
```

If a model ID is already in Bedrock format (contains `us.anthropic.`), it passes through unmapped. This provides backwards compatibility during migration.

### Relay class

```python
class Relay:
    def __init__(
        self,
        backend: str = "gateway",
        # Gateway config
        gateway_url: str = "",
        gateway_api_key: str = "",
        # Bedrock config
        aws_access_key: str = "",
        aws_secret_key: str = "",
        aws_region: str = "us-east-1",
        # Resilience
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        # Observability
        on_usage: Callable[[UsageEvent], Awaitable[None]] | None = None,
    ): ...

    @classmethod
    def from_env(cls, **overrides) -> "Relay": ...

    @classmethod
    def from_settings(cls, settings, **overrides) -> "Relay": ...

    async def complete(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        system: str | None = None,
        temperature: float | None = None,
        tools: list[dict] | None = None,
        tool_choice: dict | None = None,
        **kwargs,
    ) -> RelayResponse: ...

    def complete_sync(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        system: str | None = None,
        temperature: float | None = None,
        **kwargs,
    ) -> RelayResponse: ...
```

The `complete()` and `complete_sync()` methods accept the same parameters as `client.messages.create()` for the most commonly used arguments. Any additional kwargs are passed through to the underlying client.

### RelayResponse

```python
@dataclass
class RelayResponse:
    raw: Message              # the anthropic.types.Message
    text: str                 # first text content block (.content[0].text)
    input_tokens: int         # raw.usage.input_tokens
    output_tokens: int        # raw.usage.output_tokens
    model: str                # the friendly model name (not the Bedrock ID)
    latency_ms: float         # wall-clock time for the call
    backend: str              # "gateway" or "bedrock"
```

### UsageEvent

```python
@dataclass
class UsageEvent:
    model: str                # friendly name
    backend: str              # "gateway" or "bedrock"
    input_tokens: int
    output_tokens: int
    latency_ms: float
    timestamp: str            # ISO 8601
    retries: int              # number of retries needed (0 = first attempt succeeded)
```

### Retry logic

Exponential backoff with jitter for transient errors:

**Retryable:** `429` (rate limit), `500`, `502`, `503`, `529` (overloaded)
**Not retryable:** `400` (bad request), `401` (auth), `404` (not found)

```
attempt 1: immediate
attempt 2: base_delay * 2^0 + jitter  (≈1s)
attempt 3: base_delay * 2^1 + jitter  (≈2s)
attempt 4: base_delay * 2^2 + jitter  (≈4s)
... capped at max_delay
```

For `429` responses, if a `retry-after` header is present, that value is used instead of the calculated delay.

All retries are logged at `WARNING` level with: attempt number, delay, HTTP status, error message.

### Structured logging

Uses Python's `logging` module under the logger name `orrery_relay`.

**Per-call log (INFO):**
```
[orrery_relay] complete model=claude-sonnet-4-6 backend=gateway tokens=152/487 latency=1243ms
```

**Retry log (WARNING):**
```
[orrery_relay] retry attempt=2/3 model=claude-sonnet-4-6 status=429 delay=2.3s
```

**Error log (ERROR):**
```
[orrery_relay] failed model=claude-sonnet-4-6 status=400 error="invalid model ID"
```

Log level configurable via `RELAY_LOG_LEVEL` env var (default: `INFO`).

### Usage tracking callback

The `on_usage` callback fires after each successful completion (including retried ones). The relay does not own storage — the consumer decides what to do:

```python
async def track_usage(event: UsageEvent):
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO llm_usage (model, backend, input_tokens, output_tokens, latency_ms, retries, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event.model, event.backend, event.input_tokens, event.output_tokens,
         event.latency_ms, event.retries, event.timestamp),
    )
    conn.commit()
    conn.close()

relay = Relay.from_env(on_usage=track_usage)
```

## Integration: Orrery orchestrator & worker

### Config changes

Both `orchestrator/src/config.py` and `worker/src/config.py` update:

```python
@dataclass(frozen=True)
class Settings:
    anthropic_backend: str = "gateway"
    gateway_url: str = ""
    gateway_api_key: str = ""
    aws_access_key: str = ""         # optional, only for bedrock mode
    aws_secret_key: str = ""         # optional, only for bedrock mode
    aws_region: str = "us-east-1"
    classification_model: str = "claude-sonnet-4-6"    # friendly name
    extraction_model: str = "claude-haiku-4-5"          # friendly name
    # ... rest unchanged
```

AWS credentials become optional — only validated when `anthropic_backend=bedrock`.

### Client instantiation sites (6 files)

Each site that creates `AsyncAnthropicBedrock(...)` switches to:

```python
from orrery_relay import Relay

relay = Relay.from_settings(settings)
response = await relay.complete(model=settings.classification_model, messages=[...], max_tokens=1024)
text = response.text
```

**Files to update:**

| File | Current pattern | Change |
|------|----------------|--------|
| `orchestrator/src/routes/ingest.py` | Creates `AsyncAnthropicBedrock`, passes to pipeline fns | Creates `Relay`, passes to pipeline fns |
| `orchestrator/src/routes/reclassify.py` | Creates `AsyncAnthropicBedrock`, calls `classify_document()` | Creates `Relay`, passes relay |
| `orchestrator/src/routes/subdomains.py` | Creates `AsyncAnthropicBedrock`, calls `run_subdomain_discovery()` | Creates `Relay`, passes relay |
| `orchestrator/src/pipeline/search/expansion.py` | Creates sync `AnthropicBedrock` | Uses `relay.complete_sync()` |
| `worker/src/jobs/extract_batch.py` | Creates `AsyncAnthropicBedrock`, calls `messages.create()` directly | Uses `relay.complete()` |
| `worker/src/jobs/simmer_general.py` | Creates `AsyncAnthropicBedrock` in helper | Uses `relay.complete()` |

### Pipeline function signatures (3 files)

Functions that receive the client as a parameter update their type hints:

| File | Current signature | New signature |
|------|------------------|---------------|
| `orchestrator/src/pipeline/classifier.py` | `client: AsyncAnthropic` | `relay: Relay` |
| `orchestrator/src/pipeline/extractor.py` | `client: AsyncAnthropic` | `relay: Relay` |
| `orchestrator/src/pipeline/subdomain_discovery.py` | `client: AsyncAnthropicBedrock` | `relay: Relay` |

Inside these functions, `await client.messages.create(...)` becomes `await relay.complete(...)`.

## Integration: simmer-sdk

### Current state

The worker passes Bedrock credentials to `refine()`:

```python
bedrock_kwargs = {
    "api_provider": "bedrock",
    "aws_access_key": settings.aws_access_key,
    "aws_secret_key": settings.aws_secret_key,
    "aws_region": settings.aws_region,
}
await refine(..., **bedrock_kwargs)
```

simmer-sdk has 8 internal client creation points across 4 files (4 direct `AsyncAnthropic()` calls, 4 via `ClaudeSDKClient`).

### Target state

`refine()` accepts a `Relay` instance:

```python
relay = Relay.from_settings(settings)
await refine(..., relay=relay)
```

simmer-sdk's internal client creation points all switch to using the passed-in relay. The `api_provider` / `aws_*` kwargs are deprecated (still accepted for backwards compat, used to construct a Relay internally if no relay is passed).

simmer-sdk depends on `orrery-relay` — during Docker build, both packages are copied in.

## Environment variables summary

### Gateway mode (the new path)

```env
ANTHROPIC_BACKEND=gateway
GATEWAY_URL=https://bedrock-gateway.2389-research-inc.workers.dev
GATEWAY_API_KEY=<token>
CLASSIFICATION_MODEL=claude-sonnet-4-6
EXTRACTION_MODEL=claude-haiku-4-5
```

### Bedrock mode (existing path, still supported)

```env
ANTHROPIC_BACKEND=bedrock
AWS_ACCESS_KEY=<key>
AWS_SECRET_KEY=<secret>
AWS_REGION=us-east-1
CLASSIFICATION_MODEL=claude-sonnet-4-6
EXTRACTION_MODEL=claude-haiku-4-5
```

Note: model names are friendly in both modes. The relay translates to Bedrock IDs internally.

### Optional

```env
RELAY_LOG_LEVEL=INFO          # DEBUG, INFO, WARNING, ERROR
RELAY_MAX_RETRIES=3
RELAY_BASE_DELAY=1.0
RELAY_MAX_DELAY=30.0
```

## Testing strategy

### Unit tests (`packages/orrery-relay/tests/`)

- **Backend selection:** Verify correct client type is created for each backend
- **Model mapping:** Verify friendly names map to correct Bedrock IDs, and Bedrock IDs pass through
- **Retry logic:** Mock client to return 429/500, verify retry count, backoff timing, jitter
- **Response wrapping:** Verify RelayResponse fields are populated correctly
- **Usage callback:** Verify on_usage fires with correct data after each completion
- **from_env:** Verify environment variable parsing for both backends
- **Sync path:** Verify complete_sync creates sync client and works correctly

### Integration tests (gated behind `RELAY_INTEGRATION_TEST=1`)

- Hit the actual gateway with a trivial prompt, verify response
- Verify model aliases resolve correctly on the gateway
- Verify error responses (bad model ID, auth failure) raise appropriately

### Orrery test updates

Existing orchestrator and worker tests that mock `AsyncAnthropicBedrock` will need to mock `Relay.complete()` instead. The test interface becomes simpler — mock one method instead of a nested `client.messages.create()`.

## Migration path

1. Build `orrery-relay` package with both backends, full test suite
2. Update orchestrator config + all 6 instantiation sites + 3 pipeline functions
3. Update worker config + 2 job files
4. Update simmer-sdk to accept `relay` parameter
5. Update Docker build to copy `packages/orrery-relay/` into both service images
6. Update `run-orchestrator.sh` env script with gateway credentials
7. Verify with existing test suites

The Bedrock path remains fully functional — flipping `ANTHROPIC_BACKEND=bedrock` restores the existing behavior with zero code changes.
