# Simmer SDK — Bedrock Support Spec

**Date:** 2026-03-27
**Purpose:** Enable simmer-sdk to use AWS Bedrock instead of direct Anthropic API
**Requester:** Noospheric Orrery orchestrator — needs simmer-sdk to run simmering jobs via Bedrock

## Problem

simmer-sdk hardcodes `anthropic.AsyncAnthropic()` in 4 places and uses `ClaudeSDKClient` (from claude-agent-sdk) in 4 places. All of these read `ANTHROPIC_API_KEY` from the environment. The Noospheric Orrery orchestrator uses AWS Bedrock (IAM credentials) instead of the direct Anthropic API.

## What Needs to Change

### 1. Add a `client_factory` parameter to `refine()`

The `refine()` function should accept an optional parameter that controls how Anthropic clients are created:

```python
async def refine(
    # ... existing params ...
    # Optional — client configuration
    api_provider: str = "anthropic",  # "anthropic" | "bedrock"
    aws_access_key: str | None = None,
    aws_secret_key: str | None = None,
    aws_region: str | None = None,
) -> SimmerResult:
```

When `api_provider="bedrock"`, all `AsyncAnthropic()` calls should use `AsyncAnthropicBedrock(aws_access_key=..., aws_secret_key=..., aws_region=...)` instead.

**Default behavior is unchanged** — `api_provider="anthropic"` uses `ANTHROPIC_API_KEY` as today.

### 2. Model ID mapping

Bedrock model IDs differ from direct API model IDs:

| Direct API | Bedrock |
|-----------|---------|
| `claude-sonnet-4-6` | `us.anthropic.claude-sonnet-4-6-v1:0` |
| `claude-haiku-4-5` | `us.anthropic.claude-haiku-4-5-v1:0` |

When `api_provider="bedrock"`, either:
- **Option A:** Auto-map direct API model IDs to Bedrock IDs (simpler for callers)
- **Option B:** Require callers to pass Bedrock model IDs (simpler implementation)

Recommend **Option A** with an internal mapping dict. Callers can still override with explicit Bedrock IDs.

### 3. Files that need changes

There are **two categories** of Anthropic client usage:

#### Category A: Direct `AsyncAnthropic()` calls (4 locations)

These create raw Anthropic clients for simple message calls. They need to swap to Bedrock when configured.

| File | Line | Function | Model Used |
|------|------|----------|-----------|
| `judge_board.py` | 118 | `compose_judges()` | `brief.clerk_model` |
| `judge_board.py` | 253 | `_deliberate_single()` | parameter `model` |
| `judge_board.py` | 482 | `_synthesize_board()` | `brief.judge_model` |
| `reflect.py` | 215 | `condense_key_change_llm()` | parameter `model` (default `claude-haiku-4-5`) |

**Fix:** Extract a helper function:

```python
# simmer_sdk/client.py (new file)
from anthropic import AsyncAnthropic, AsyncAnthropicBedrock

def create_client(brief) -> AsyncAnthropic | AsyncAnthropicBedrock:
    if brief.api_provider == "bedrock":
        return AsyncAnthropicBedrock(
            aws_access_key=brief.aws_access_key,
            aws_secret_key=brief.aws_secret_key,
            aws_region=brief.aws_region,
        )
    return AsyncAnthropic()

def map_model_id(model: str, api_provider: str) -> str:
    if api_provider != "bedrock":
        return model
    BEDROCK_MAP = {
        "claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6-v1:0",
        "claude-haiku-4-5": "us.anthropic.claude-haiku-4-5-v1:0",
        "claude-sonnet-4-20250514": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "claude-haiku-4-20250514": "us.anthropic.claude-haiku-4-20250514-v1:0",
    }
    return BEDROCK_MAP.get(model, model)  # pass through if not in map
```

Then replace all `anthropic.AsyncAnthropic()` with `create_client(brief)` and wrap model IDs with `map_model_id()`.

#### Category B: `ClaudeSDKClient` calls (4 locations)

These use the claude-agent-sdk which manages its own Anthropic client internally. The `ClaudeAgentOptions` takes a `model` parameter but does NOT take API provider configuration.

| File | Line | Function | Model Used |
|------|------|----------|-----------|
| `generator.py` | 110 | `dispatch_generator()` | `brief.generator_model` |
| `judge.py` | 181 | `dispatch_judge()` | `brief.judge_model` |
| `judge_board.py` | 225 | `_dispatch_single_panelist()` | `brief.judge_model` |
| `reflect.py` | 651 | `dispatch_reflect()` | parameter `model` |

**Fix options:**

1. **Environment-based:** When `api_provider="bedrock"`, set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` environment variables before calling `ClaudeSDKClient`. The claude-agent-sdk may pick these up if it supports Bedrock.

2. **Check if claude-agent-sdk supports Bedrock:** If `ClaudeAgentOptions` has an `api_provider` or `aws_*` parameter, use it directly.

3. **Replace ClaudeSDKClient with direct API calls:** For Bedrock mode, bypass claude-agent-sdk and use `AsyncAnthropicBedrock` directly with the same prompts. More work but guaranteed to work.

**Recommendation:** Check option 2 first. If claude-agent-sdk doesn't support Bedrock, use option 1 (env vars) as the quick fix.

### 4. SetupBrief changes

Add Bedrock fields to `SetupBrief` dataclass:

```python
@dataclass
class SetupBrief:
    # ... existing fields ...
    api_provider: str = "anthropic"
    aws_access_key: str | None = None
    aws_secret_key: str | None = None
    aws_region: str | None = None
```

These get populated from `refine()` parameters and threaded through to all dispatch functions.

### 5. Threading the config

The Bedrock config needs to reach all 8 client creation points. The `brief` object is already passed to most functions. For the two functions that take a bare `model` parameter instead of `brief`:

- `condense_key_change_llm()` in `reflect.py:201` — add `brief` parameter or `api_provider` + credentials
- `_deliberate_single()` in `judge_board.py:240` — already receives `brief` indirectly through the caller

## How the Orrery Orchestrator Will Call It

```python
from simmer_sdk import refine

result = await refine(
    artifact=str(seed_path),
    criteria={...},
    iterations=5,
    judge_mode="board",
    output_dir=specs_dir / "general_golden",
    # Bedrock config
    api_provider="bedrock",
    aws_access_key=settings.aws_access_key,
    aws_secret_key=settings.aws_secret_key,
    aws_region=settings.aws_region,
    # Model IDs — can use direct API names, auto-mapped to Bedrock
    generator_model="claude-sonnet-4-6",
    judge_model="claude-sonnet-4-6",
    clerk_model="claude-haiku-4-5",
)
```

## Scope

- **In scope:** Add Bedrock support as an alternative to direct Anthropic API
- **In scope:** Auto-map model IDs between direct API and Bedrock formats
- **In scope:** Default behavior unchanged (direct API with ANTHROPIC_API_KEY)
- **Out of scope:** Other providers (Google, OpenAI, etc.)
- **Out of scope:** Changing the simmer loop logic, judge strategy, or evaluation flow

## Testing

- Existing tests should still pass (default provider = "anthropic")
- Add tests that mock `AsyncAnthropicBedrock` and verify it's used when `api_provider="bedrock"`
- Verify model ID mapping works for known models and passes through unknown ones
