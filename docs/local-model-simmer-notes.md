# Working notes — local (Ollama/gemma4) simmer pipeline

Branch: `local-model-simmer-fixes`. Goal: get the fully-local tier (Ollama + gemma4)
running the full pipeline (classify → extract → simmer-refine spec → re-extract →
normalize) and fix where local models diverge from the cloud (Sonnet/Haiku) path.

Models: `gemma4:26b` = classification / judge / generator / clerk. `gemma4:e4b` = extraction.

## How to run the local stack

```bash
colima start --cpu 4 --memory 8 --disk 60          # or Docker Desktop
docker-compose -f docker-compose.yml -f docker-compose.ollama.yml build orchestrator worker
docker-compose -f docker-compose.yml -f docker-compose.ollama.yml up -d
# orchestrator :8100, frontend :3100, host Ollama reached via host.docker.internal
```

`docker-compose.ollama.yml` overrides the backend to Ollama and writes to an isolated
workspace (`/data/local/...`) so the existing Bedrock graph is untouched. The bedrock
`.env` is left intact (explicit `environment:` keys override it).

## Bugs found & fixed (committed on this branch)

1. **Relay dropped reasoning-model output** — `orrery-relay/relay.py` `_complete_ollama`
   only read `message.content`. gemma4:26b is a reasoning model; Ollama puts its
   thinking in a separate `thinking` field and, with a tight `num_predict`, the answer
   never lands in `content` → empty → classification returned `{}` → **no domains**.
   Fix: send `"think": false`. (Confirmed: clean JSON in ~69 tokens; harmless to e4b.)
   Bumping `num_predict` to 4096 also "works" but costs ~10–20× tokens/latency for no
   quality gain — `think:false` is the cure, headroom is just belt-and-suspenders.

2. **Worker missing `openai`** — simmer-sdk's Ollama agent loop (`local_agent.py`) needs
   the `openai` client, declared only under its `[local]` extra. Worker Dockerfile
   installed `simmer-sdk` without it → every board judge died `No module named 'openai'`.
   Fix: `simmer-sdk[local]` in `worker/Dockerfile`.

3. **Docker SIGILL is a myth (stale comment)** — `orchestrator/Dockerfile.local` already
   fixes it via `NUMBA_CPU_NAME=generic` (numba#10388) + native arm64 CPU torch wheels.
   sentence-transformers/UMAP work in-container as long as the image is **built locally**
   (colima builds arm64 natively). Don't pull the `:latest` ghcr image (amd64 → Rosetta
   SIGILL). TODO: update the misleading comments in `docker-compose.yml`.

## The core finding: where local models diverge from Sonnet

The simmer generator/judge run the SAME prompts as the cloud path — only the engine
differs (`run_local_agent`, an OpenAI tool-loop, vs `ClaudeSDKClient`). The local path
is **not** more decomposed; the decomposition in simmer-sdk's `local-models-guide.md` is
documentation, not wired into `refine()`. gemma4:26b is weak at the self-directed
agentic work the design assumes Claude can do. Two concrete failures:

### Phase 1 — golden set (FIXED on this branch)
- **Agentic generator stalls**: gemma4 loops on the `Read` tool (re-issues the identical
  call), hits simmer-sdk's duplicate-call guard, breaks out **before** writing or before
  the tool-free salvage turn → 0-byte candidate → judge scores it 1.0. Trajectory was
  `6.7 → 1.0(stall) → 7.3`.
- Root absurdity: the worker already has the sample chunks in memory, writes them to
  disk, then the prompt tells the model to discover & re-read them via tools. Pointless.
- **Fix shipped**: `_build_golden_set_mapreduce()` in `worker/src/jobs/simmer_general.py`
  replaces the agentic golden generation with **map (per-chunk extraction, one small
  call, no tools) → reduce (Python merge)**. Deterministic, 0 stalls, ~50s, 95 entities
  vs the agentic run's 44. Mirrors how the judge **board** decomposes work.
- **Canonicalization REDUCE (DONE)**: per-chunk extraction has no global view, so fragments
  (`harper`/`harper reed`), typos (`commer`/`cummer`), acronym pairs (`lvmh`/`louis vuitton
  moet hennessy`) and non-entities (emails, vague phrases) survive the exact-`(name,type)`
  merge. Tested in isolation: the existing **embedding** normalizer barely helped (MiniLM
  cosine is weak on short names/typos/acronyms — 95→93). An **LLM canonicalization** pass
  (gemma4:26b, the existing pipeline's Tier-3 idea as one global pass) cleanly merged them
  (95→71). Shipped as `_canonicalize_golden` — batched **per type** so each call stays in
  the output-token budget (one call over hundreds of entities overflows → parse-fail →
  fallback to raw). Map now uses **e4b** (was 26b: ~20x faster, less over-extraction).

### Phase 2 — extraction spec (DONE — shared rules-loop)
- Phase 2 is supposed to produce a **generalized extraction prompt**: type definitions +
  INCLUDE/EXCLUDE rules + illustrative (non-exhaustive) examples that work on unseen docs.
- **What the local model actually produced**: just the golden set passed through — a
  hardcoded 95-entity JSON list, **0 rule-lines**, no generalization. (The previous
  agentic local run did the same: 44-entity list, 0 rules.) gemma4 never makes the
  abstraction leap; it relists entities. The judge's ASI even said "lookup to taxonomy
  transition" but it didn't take.
- **Proof the design is sound (it's a local-model gap, not a design flaw)**: the
  Sonnet/Bedrock simmer spec (in `data/workspaces/default/orrery.db`, scored 9.3) is a
  real generalized spec — 19 rule-lines, only illustrative names, explicit INCLUDE/EXCLUDE
  rules ("EXCLUDE vague descriptors like 'ease','quality'", "extract 'personal branding'
  whole, not 'branding'"), and "examples are NOT exhaustive". Those very EXCLUDE rules
  would have prevented our local golden's noise. The committed `orchestrator/specs/
  general_text.md` is the same shape (type table + decision tree). So cloud Phase 2 works
  as designed; gemma4 can't generalize in one self-directed shot.

**Phase 2 fix SHIPPED** (`_refine_spec_rules`, shared by both simmers): scaffold the
abstraction instead of asking the weak model to do it in one self-directed agentic shot.
1. Seed from a **rules TEMPLATE** (type defs + empty INCLUDE/EXCLUDE), never the golden list.
2. Loop: **extract** per chunk (e4b, single-shot, no agentic loop) → **score by F1 against
   the golden DETERMINISTICALLY** (no LLM judge) → **revise rules** (gemma4:26b, one call,
   given concrete misses/false-positives, forbidden from listing entity names). Keep best F1.
3. Validated on the meetings domain: spec went from 44 embedded entity names / 3 rule-lines
   → **14 rule-lines, 0 hardcoded entities** with generic illustrative examples. F1 0.56 →
   0.71 (rollback protects best). The Sonnet-9.3 shape, on the local path.

Note: scores are NOT comparable across simmer runs — judge against artifact *content*
(rules vs list, coverage, cleanliness), not the composite numbers.

## Critical realization: simmer_domain is the production path
`simmer_general` is **manual-only** (`POST /simmer/general`); nothing auto-triggers it.
`simmer_domain` is auto-fired from `ingest.py` when a domain crosses the 20-doc threshold —
**that's the path that actually runs.** Both phases' fixes now live in shared helpers in
`simmer_general.py` and are imported by `simmer_domain.py`, so the production path gets them.
(`simmer_domain_image.py` still uses the old agentic flow — future work if image domains matter.)

## Files touched on this branch
- `packages/orrery-relay/src/orrery_relay/relay.py` — `think:false`
- `worker/Dockerfile` — `simmer-sdk[local]`
- `worker/src/jobs/simmer_general.py` — shared helpers: `_build_golden_set_mapreduce` (map only),
  `_discover_domain_types`, `_refine_spec_rules`. (The canonicalize REDUCE was removed — dedup /
  type reconciliation is the normalization step's job, issue #26.)
- `worker/src/jobs/simmer_domain.py` — additive: discovers domain-specific types and extracts
  ONLY those (base types handled by the general pass); uses the shared Phase 1 & 2 helpers.
- `docker-compose.ollama.yml` — local Ollama/gemma4 override (new)
- prototypes (scratchpad, not committed): `mapreduce_golden.py`, `golden_reduce_llm.py`,
  `phase2_rules.py` — standalone A/B harnesses

## Remaining / future
- `simmer_domain_image.py` not yet ported to the decomposed flow.
- A clean extraction of the shared helpers into a dedicated `golden.py`/`spec.py` module
  (currently `simmer_domain` imports private helpers from `simmer_general`).
- Domain-type discovery is non-deterministic (a domain proposes a different type set each run).
  NOT important: auto-simmer fires once per domain (`spec_version is None`); every re-simmer is
  a deliberate regenerate, so a fresh type set is expected. Granularity grows via subdomain
  subdivision (`subdomain_discovery.py`) + the spec cascade — each node gets its own stable
  types — NOT by expanding a single node's type list. Persist-types-once is a possible polish.
