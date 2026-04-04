# Noospheric Orrery — Fully Self-Hosted with Local Models

*Research spec for a design/research agent. Self-contained — describes
all interfaces, current architecture, and open questions.*

---

## Goal

Run the entire Noospheric Orrery pipeline with **zero cloud API keys**.
No Anthropic, no AWS, no Google Cloud. Just Docker + local LLMs.

Currently the system has three tiers:
1. **Cloud** — Firestore + Firebase Auth + Bedrock Sonnet/Haiku + Vertex AI embeddings
2. **Local with API** — SQLite + noop auth + Bedrock/Gateway Sonnet/Haiku + sentence-transformers
3. **Fully self-hosted** (this spec) — SQLite + noop auth + Ollama local models + sentence-transformers

Tier 3 means a user can `docker compose up` and have a working knowledge
graph system on their laptop. No internet required after initial model download.

---

## What Uses Cloud LLMs Today

Every LLM call goes through `orrery-relay`, a shared SDK at
`packages/orrery-relay/`. The Relay class abstracts the backend:

```python
from orrery_relay import Relay

relay = Relay(
    backend="bedrock",          # or "gateway"
    aws_access_key="...",
    aws_secret_key="...",
    aws_region="us-east-1",
)
```

### Relay.complete_structured() — The Key Interface

All pipeline LLM calls use this method. It uses Anthropic's tool use
to guarantee valid JSON output matching a schema:

```python
result = await relay.complete_structured(
    model="claude-sonnet-4-6",      # model identifier
    messages=[                       # standard chat messages
        {"role": "user", "content": "Classify this document..."}
    ],
    max_tokens=1024,
    schema={                         # JSON Schema for output
        "type": "object",
        "properties": {
            "primary_domain": {"type": "string"},
            "secondary_domains": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": ["primary_domain", "secondary_domains", "confidence"],
    },
    tool_name="classify_document",   # synthetic tool name
    tool_description="Classify...",  # guides the model
    system=None,                     # optional system prompt
    temperature=None,                # optional
)
# result is a dict matching the schema — never raises JSONDecodeError
```

**Under the hood:** Creates a tool definition from the schema, forces
`tool_choice={"type": "tool", "name": tool_name}`, extracts the tool
input from the response. The model is forced to call the tool, and the
input is validated against the schema by the API.

### Relay.complete() — Raw Text Calls

Used by simmer-sdk indirectly (via AsyncAnthropicBedrock). Returns
free-form text, not structured output.

```python
response = await relay.complete(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "..."}],
    max_tokens=4096,
    system="You are...",
    tools=[...],            # optional tool definitions
    tool_choice={...},      # optional
)
# response.text = the raw text response
# response.raw = the full API response object
```

### Current Relay Backends

```python
# In packages/orrery-relay/src/orrery_relay/relay.py

class Relay:
    def __init__(self, backend="gateway", gateway_url="", gateway_api_key="",
                 aws_access_key="", aws_secret_key="", aws_region="us-east-1", ...):
        if backend == "gateway":
            self._async_client = AsyncAnthropic(base_url=gateway_url, api_key=gateway_api_key)
        elif backend == "bedrock":
            self._async_client = AsyncAnthropicBedrock(
                aws_access_key=aws_access_key, aws_secret_key=aws_secret_key, aws_region=aws_region)
```

Both backends use the Anthropic Python SDK (`anthropic` package).
Adding Ollama would need a different client library.

---

## The Four LLM Tasks

### 1. Classification (Sonnet-class)

**File:** `orchestrator/src/pipeline/classifier.py`

**What it does:** Given a document excerpt and existing domain taxonomy,
assigns primary + secondary domain paths.

**Schema:**
```json
{
  "primary_domain": "history/technology/computing",
  "secondary_domains": ["philosophy/epistemology"],
  "confidence": 0.85
}
```

**Prompt complexity:** Medium. Needs to understand document content,
match against existing taxonomy, create new domain paths when appropriate.
Taxonomy can have 30+ domains.

**Quality requirements:** Moderate. Misclassification is recoverable
(reclassify endpoint exists). But bad classification cascades — wrong
domain means wrong spec applied for extraction.

**Local model minimum:** 8B with good instruction following. 70B preferred.

### 2. Extraction (Haiku-class)

**File:** `orchestrator/src/pipeline/extractor.py`

**What it does:** Given a text chunk and an extraction spec, extracts
named entities with types.

**Schema:**
```json
{
  "entities": [
    {"name": "alan turing", "type": "Person"},
    {"name": "bletchley park", "type": "Location"}
  ]
}
```

**Prompt complexity:** Lower. Follows a detailed spec. The spec tells it
exactly what types to extract with examples and exclusions.

**Quality requirements:** High precision matters — false positives
create noise. Recall is improved by simmering (better specs).

**Local model minimum:** 7-8B with good JSON output. This is the
highest-volume call (runs per chunk, ~50 chunks per document).

### 3. Search Expansion (Haiku-class)

**File:** `orchestrator/src/pipeline/search/expansion.py`

**What it does:** Expands a search query into 3-5 sub-queries (synonyms,
related concepts, more specific versions).

**Schema:**
```json
{
  "sub_queries": ["turing machine definition", "alan turing computation", "halting problem"]
}
```

**Prompt complexity:** Low. Pure language understanding.

**Quality requirements:** Low. Search still works without expansion
(`expand=false`). This is a nice-to-have enhancement.

**Local model minimum:** Any 7B model. Can be disabled entirely.

### 4. Subdomain Discovery (Sonnet-class)

**File:** `orchestrator/src/pipeline/subdomain_discovery.py`

**What it does:** Given a document's entities and current domains,
proposes more specific subdomains.

**Schema:**
```json
{
  "new_subdomains": ["business/fundraising/seed_round"]
}
```

**Prompt complexity:** Medium. Needs taxonomy understanding.

**Local model minimum:** Same as classification — 8B minimum, 70B preferred.

---

## The Hard Part: Simmer-SDK

### How Simmering Works Today

The simmer-sdk (`packages/simmer-sdk/` or external `simmer-sdk` repo)
runs an iterative refinement loop:

```
for each iteration:
    1. Generator (Sonnet) — improves the artifact based on feedback
    2. Judge Board (2x Sonnet agents) — evaluates the artifact
       - Each judge has Read/Grep/Glob tools
       - Judges read sample documents to evaluate
       - Judges deliberate (see each other's scores)
       - Synthesis produces consensus scores + improvement direction
    3. Reflect — updates trajectory, handles regression
```

### The Judge Board Problem

The judge board uses **Claude Agent SDK** (`claude_agent_sdk`), which
spawns **Claude CLI** (`@anthropic-ai/claude-code`) processes. Each
judge is a full Claude Code agent with file access.

```python
# In simmer-sdk/src/simmer_sdk/judge_board.py
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

client = ClaudeSDKClient(ClaudeAgentOptions(
    model="claude-sonnet-4-6",
    max_turns=5,
))
```

This is **deeply coupled to Claude**. The Agent SDK only works with
Anthropic models via their API or Bedrock. There is no Ollama backend.

### Options for Local Simmering

**Option A: Simplified single-call judge (no agent tools)**

Instead of spawning agent processes, send one big prompt with all the
context inlined:

```
Here is the extraction spec:
{spec_content}

Here are 10 sample documents:
{doc1}
{doc2}
...

Evaluate the spec against these criteria:
- coverage: Does it capture all entity types?
- precision: Are there false positives?
- domain_specificity: Are types specific to this domain?

Return scores 1-10 with evidence and improvement suggestions.
```

No tool use needed. Works with any LLM. Quality is lower (judge can't
explore files dynamically) but functional.

**Estimated quality impact:** 70-80% of board quality. The main loss
is the judge's ability to discover patterns by reading documents
interactively. With documents inlined, the context window becomes the
limiting factor.

**Option B: Local agent framework with Ollama**

Use a local agent framework that supports Ollama + tool use:
- `smolagents` (HuggingFace) — supports Ollama, has tool use
- `langgraph` — flexible agent graphs, any LLM backend
- `instructor` — structured output from any OpenAI-compatible API
- Custom: Ollama API supports function calling for Llama 3.1+

The judge would still have Read/Grep/Glob tools but use a local model
instead of Claude. The simmer-sdk would need a pluggable judge backend.

**Estimated quality impact:** 80-90% of board quality with 70B models.
50-60% with 8B models (they struggle with multi-step reasoning).

**Option C: Hybrid — local everything except simmering**

Classification, extraction, search expansion all use local models.
Simmering still uses cloud API (it's the least frequent operation).
A user simmers once per domain, then extracts many documents locally.

**Practical impact:** A user could ingest 1000 documents locally, but
needs an API key to create/refine their extraction spec. Acceptable
tradeoff for many use cases.

---

## Adding an Ollama Backend to Relay

### The Interface

```python
relay = Relay(
    backend="ollama",
    ollama_url="http://localhost:11434",   # Ollama server
)

# Same calls work:
result = await relay.complete_structured(
    model="llama3.1:8b",
    messages=[...],
    schema=EXTRACTION_SCHEMA,
)
```

### Implementation Considerations

**1. Client library:**
Ollama has an official Python client (`ollama` package) and also exposes
an OpenAI-compatible API at `/v1/chat/completions`. The OpenAI-compatible
endpoint supports function calling for models that support it.

Using the OpenAI-compatible endpoint means we could use `openai` Python
SDK, which makes this backend work with any OpenAI-compatible provider
(Ollama, vLLM, llama.cpp server, etc.).

**2. Tool use / structured output:**
Ollama supports function calling for Llama 3.1+, Mistral, and some other
models. The format matches OpenAI's function calling spec. But reliability
varies by model — smaller models may not always follow the schema.

Fallback strategy: if tool use fails, parse the raw text response as JSON
with the same JSONL fallbacks we used to have.

**3. Model name mapping:**
The Relay currently maps friendly names to Bedrock IDs. For Ollama, the
model name IS the Ollama tag:
```
"llama3.1:8b"    → "llama3.1:8b"     (pass-through)
"mistral:7b"     → "mistral:7b"
"qwen2.5:72b"    → "qwen2.5:72b"
```

**4. Async support:**
Relay uses `async/await`. The Ollama Python client supports async.
The OpenAI client also supports async.

### Proposed Relay Changes

```python
# In relay.py __init__:
elif backend == "ollama":
    from openai import AsyncOpenAI
    self._async_client = AsyncOpenAI(
        base_url=f"{ollama_url}/v1",
        api_key="ollama",  # Ollama doesn't need a real key
    )
    self._is_openai_compat = True
```

The `complete()` and `complete_structured()` methods would need to handle
the OpenAI response format (slightly different from Anthropic):
- Anthropic: `response.content[0].text` or `response.content[0].input`
- OpenAI: `response.choices[0].message.content` or `response.choices[0].message.tool_calls[0].function.arguments`

---

## Embedding: Already Local

Sentence-transformers (`all-MiniLM-L6-v2`, 384-dim) already works locally.
No changes needed. Used for:
- UMAP domain layout
- Entity similarity for normalization
- FAISS search (SQLite mode)

---

## Resource Requirements

### Extraction-only (most common use case)
- **Model:** Llama 3.1 8B (Q4 quantized ~4.5GB)
- **VRAM:** 6GB
- **RAM:** 8GB total system
- **Works on:** M1 Mac with 8GB, any GPU with 6GB+

### Classification + extraction
- **Model:** One 8B model handles both (different prompts)
- **Same requirements as above**

### Full simmering (Option A — simplified judge)
- **Model:** 70B for generation, 8B for extraction
- **VRAM:** 40GB+ for 70B (or CPU offload with 64GB RAM)
- **Realistic on:** M1 Max/Ultra with 64GB, workstation GPUs
- **Alternative:** Use 8B for everything, accept lower quality

### Recommended default configuration
```env
# .env for fully self-hosted mode
LLM_BACKEND=ollama
OLLAMA_URL=http://host.docker.internal:11434
CLASSIFICATION_MODEL=llama3.1:8b
EXTRACTION_MODEL=llama3.1:8b
SIMMER_MODE=simplified    # single-call judge, no agent tools
```

---

## Implementation Plan

### Phase 1: Ollama backend for Relay
**Scope:** Add `backend="ollama"` to orrery-relay using OpenAI-compatible API.
Classification, extraction, search expansion all work locally.
Simmering still needs cloud API (Option C hybrid).

**Files:**
- `packages/orrery-relay/src/orrery_relay/relay.py` — add ollama backend
- `packages/orrery-relay/src/orrery_relay/backends.py` — model name pass-through
- `orchestrator/src/config.py` — add OLLAMA_URL setting
- `docker-compose.sqlite.yml` — add ollama service or document external setup

**Verification:** Upload a doc, classify with Llama 3.1 8B, extract
entities, render orrery. Compare entity quality vs Haiku.

### Phase 2: Simplified local simmering
**Scope:** Add a `judge_mode="local"` to simmer-sdk that inlines documents
into the prompt instead of using agent tools. Works with any LLM.

**Files:**
- `simmer-sdk` — new judge mode
- `worker/src/jobs/simmer_general.py` — pass `judge_mode` based on config
- Config: `SIMMER_MODE=simplified` env var

**Verification:** Run a general simmer on 10 docs using Ollama. Compare
spec quality vs cloud simmering.

### Phase 3: Docker compose with Ollama
**Scope:** Add Ollama as a Docker service in the compose file. Pre-pull
models on first run. Full self-hosted experience.

```yaml
services:
  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama
  orchestrator:
    environment:
      - LLM_BACKEND=ollama
      - OLLAMA_URL=http://ollama:11434
```

### Phase 4 (stretch): Full agent simmering with local models
**Scope:** Integrate smolagents or similar with Ollama for tool-using
judge agents. Full simmer quality with local models.

---

## Open Questions for Research

1. **Ollama function calling reliability** — How reliably do Llama 3.1 8B
   and Mistral 7B follow JSON schemas via tool use? What's the failure rate?
   Do we need parsing fallbacks?

2. **Context window for simplified judges** — If we inline 10 documents
   (each ~2000 chars = ~500 tokens) + spec + criteria, that's ~7000 tokens
   input. Can 8B models handle this well? What about 70B?

3. **Quality benchmarks** — Has anyone compared entity extraction quality
   between Haiku and Llama 3.1 8B on similar tasks? What about
   classification accuracy?

4. **Ollama tool use format** — Does Ollama's function calling support
   nested schemas (arrays of objects)? Our extraction schema has
   `entities: [{name, type}]` — is this handled correctly?

5. **vLLM / llama.cpp server compatibility** — If we use the OpenAI-compatible
   API, does this also work with vLLM and llama.cpp server? That would
   make the backend work with any local inference engine.

6. **GGUF quantization impact** — How much does Q4 vs Q8 quantization
   affect extraction quality for structured output tasks?

7. **smolagents + Ollama** — Can smolagents run a tool-using agent with
   Ollama backend reliably enough for judge board deliberation?

8. **Memory management** — Can Ollama serve two models simultaneously
   (8B for extraction + 70B for classification)? Or does it swap?
   What's the latency impact?
