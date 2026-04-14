# Simmer-SDK: Replace Claude Agent SDK with Direct API Agent Loop

Research findings and migration plan for the simmer agent.

---

## Problem

The simmer-sdk's board judge uses the Claude Agent SDK (`ClaudeSDKClient` from `claude_agent_sdk`) to dispatch individual judge panelists. This spawns the Claude Code CLI as a Node.js subprocess per judge. In our Docker worker, this causes:

1. **Hangs**: The worker freezes mid-simmer and never completes. We've reproduced this multiple times. The last run hung after extraction_spec iteration 3 with Node.js processes alive but producing no output.
2. **12s startup overhead**: Each new `ClaudeSDKClient` session spawns a full CLI process. With 2 judges + deliberation, that's 24s+ of pure startup per iteration.
3. **Zombie processes**: Failed CLI spawns leave zombies that block subsequent attempts.

## Root Cause Research

The Claude Agent SDK is designed for interactive/CLI use (IDE integrations, CI pipelines), not server-side production in Docker. Evidence:

| Issue | Source |
|-------|--------|
| `stream-json` output mode intermittently hangs — 2/12 runs with 6 concurrent instances | [claude-code#39700](https://github.com/anthropics/claude-code/issues/39700) |
| SDK subprocess hangs on initialize, leaves zombies at 60-70% CPU | [claude-code#18666](https://github.com/anthropics/claude-code/issues/18666) |
| `query()` timeout regression in Docker (works on host) | [claude-code#42884](https://github.com/anthropics/claude-code/issues/42884) |
| Prompt caching disabled for SDK consumers (only REPL gets it) | [claude-code#39732](https://github.com/anthropics/claude-code/issues/39732) |
| Docker `spawn ENOENT` failures | [claude-code#14464](https://github.com/anthropics/claude-code/issues/14464) |
| Python SDK broken in Docker when `DEBUG` env is set | [claude-agent-sdk-python#347](https://github.com/anthropics/claude-agent-sdk-python/issues/347) |
| No built-in timeouts, retries, or health checks | Multiple issues |
| `claude serve` (persistent API mode) requested but not implemented | [claude-code#37211](https://github.com/anthropics/claude-code/issues/37211) |

## What the Judges Actually Need

The board judges need to:
1. Read files (candidate spec, evaluator output, raw extraction results)
2. Optionally grep/search through files
3. Score against criteria and write reasoning

That's it. This is standard LLM tool_use — the Anthropic API supports it natively. No CLI subprocess needed.

## The Solution Already Exists in Simmer-SDK

The simmer-sdk already has **two dispatch paths** in `_dispatch_single_panelist()` (in `judge_board.py`):

```python
# Path 1: Ollama/local mode — Python-native agent loop
if brief.api_provider == "ollama":
    from simmer_sdk.local_agent import run_local_agent
    result_text = await run_local_agent(
        prompt=prompt,
        model=brief.judge_model,
        ollama_url=brief.ollama_url,
        tools=["Read", "Grep", "Glob"],
        cwd=workspace_path or brief.output_dir,
        max_turns=25,
    )
    # ... works perfectly, no subprocess

# Path 2: Cloud/Bedrock mode — spawns Claude CLI subprocess
options = ClaudeAgentOptions(
    tools=["Read", "Grep", "Glob"],
    model=map_model_id(brief.judge_model, brief),
    permission_mode="bypassPermissions",
    ...
)
async with ClaudeSDKClient(options=options) as client:
    await client.query(prompt)
    # ... this is what hangs
```

`run_local_agent` in `local_agent.py` is a clean Python agent loop that:
1. Sends the prompt to the model
2. If the model requests tool calls (Read/Grep/Glob), executes them in Python
3. Returns tool results to the model
4. Repeats until the model produces a final text response

This works perfectly for Ollama. The same pattern works for the Anthropic API — just swap the Ollama HTTP call for `client.messages.create()`.

## Migration Plan

### Option A: Add `run_api_agent` alongside `run_local_agent` (recommended)

Create `api_agent.py` that mirrors `local_agent.py` but uses the Anthropic async client:

```python
async def run_api_agent(
    prompt: str,
    client: anthropic.AsyncAnthropic,  # or relay
    model: str,
    tools: list[str],
    cwd: str,
    max_turns: int = 25,
) -> str:
    """Agent loop using direct Anthropic API with tool_use."""
    tool_defs = build_tool_definitions(tools)  # Read, Grep, Glob as API tool schemas
    messages = [{"role": "user", "content": prompt}]
    
    for _ in range(max_turns):
        response = await client.messages.create(
            model=model,
            max_tokens=8192,
            messages=messages,
            tools=tool_defs,
        )
        
        # If no tool use, we're done
        if response.stop_reason == "end_turn":
            return extract_text(response)
        
        # Execute tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input, cwd)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
        
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
    
    return extract_text(response)  # max turns reached
```

Then update `_dispatch_single_panelist`:

```python
if brief.api_provider == "ollama":
    result_text = await run_local_agent(...)
else:
    # Direct API — no subprocess
    from simmer_sdk.api_agent import run_api_agent
    client = create_async_client(brief)
    result_text = await run_api_agent(
        prompt=prompt,
        client=client,
        model=map_model_id(brief.judge_model, brief),
        tools=["Read", "Grep", "Glob"],
        cwd=workspace_path or brief.output_dir,
        max_turns=25,
    )
```

### Option B: Unify into a single agent loop with pluggable backend

Refactor `run_local_agent` to accept a generic completion function:

```python
async def run_agent_loop(
    prompt: str,
    complete_fn: Callable,  # (messages, tools) -> response
    tools: list[str],
    cwd: str,
    max_turns: int = 25,
) -> str:
```

Then `run_local_agent` and `run_api_agent` are just thin wrappers that provide different `complete_fn` implementations.

## What to Remove

Once `run_api_agent` works:
1. Remove `ClaudeSDKClient` import and usage from `judge_board.py`
2. Remove `claude_agent_sdk` from dependencies
3. Remove `claude-code` CLI installation from worker Dockerfile (saves ~200MB image size)
4. Remove Node.js installation from worker Dockerfile

## What to Keep

- `run_local_agent` for Ollama mode (already works)
- The tool implementations (Read, Grep, Glob) in Python — these are shared between local and API agents
- The judge board orchestration (compose → score → deliberate → synthesize) — only the dispatch method changes

## Performance Comparison

| Metric | Claude Agent SDK | Direct API agent loop |
|--------|-----------------|----------------------|
| Startup per judge | ~12s (CLI spawn) | ~0s (HTTP call) |
| Per-turn latency | ~1-3s | ~1-3s |
| Hang risk | 15-20% under concurrency | ~0% (standard HTTP) |
| Prompt caching | Disabled | Available |
| Docker reliability | Multiple known bugs | Standard HTTP client |
| Image size impact | +200MB (Node.js + CLI) | 0 |
| Zombie processes | Yes (documented) | No |

## Files to Modify in simmer-sdk

| File | Change |
|------|--------|
| `src/simmer_sdk/api_agent.py` | New file — API-backed agent loop |
| `src/simmer_sdk/judge_board.py` | Replace `ClaudeSDKClient` with `run_api_agent` |
| `src/simmer_sdk/local_agent.py` | Extract shared tool execution into common module |
| `pyproject.toml` | Remove `claude-agent-sdk` dependency |

## Files to Modify in Noospheric-Orrery (after SDK update)

| File | Change |
|------|--------|
| `worker/Dockerfile` | Remove Node.js + Claude CLI installation (~10 lines, ~200MB savings) |
| `worker/entrypoint.sh` | Remove Claude CLI setup |

## Testing

1. Run a domain simmer end-to-end in Docker — should complete all iterations without hanging
2. Verify judges still read files correctly (evaluator output, candidate specs)
3. Verify scores match between old and new dispatch (same judge prompt, same tools)
4. Check that Ollama mode still works via `run_local_agent`
