# Agentic vs Decomposed Simmer — Cost / Time / Quality Findings

**Date:** 2026-06-29
**Branch:** `experiment/agentic-vs-decomposed-cost`
**Design:** `2026-06-29-agentic-vs-decomposed-cost-test-design.md` (same dir)
**Status:** Complete, n=1 (one domain, one run per arm). Directional, not statistically significant.

## TL;DR

On Claude, for one real domain simmer, the **decomposed (shipped) flow** beat the **old agentic
`refine()` flow** on every axis we measured:

- **~27× cheaper** ($0.46 vs $12.58)
- **~3.8× faster** (5.4 min vs 20.4 min)
- **Comparable-to-better output quality** — the decomposed spec generalizes better and the golden is
  more domain-useful; the *expensive* agentic flow actually **overfit** (it hardcoded corpus-specific
  names into its extraction rules).

The agentic flow's cost did not buy better quality here — it correlated with overfitting. For Claude,
the decomposition built for local models looks like the better default, not a compromise.

## Method (summary — full design in the companion doc)

Both arms ran the **same task**: domain `business/venture_capital/vc_firms`, a DB copy trimmed to the
**same pinned 10 chunks** (so the old flow's `ORDER BY RANDOM() LIMIT 10` is deterministic), seed + 2
iterations, **Sonnet 4.6 + Haiku 4.5**, **bedrock**. Only the flow architecture differed:

- **Agentic:** the pre-decomposition `run_simmer_domain` restored verbatim from commit `58498de` —
  two `simmer_sdk.refine()` calls (golden + spec), board judging, tool-using agent reading the chunks.
  Transport note: today's SDK runs that identical agentic strategy via a **direct-API tool-use loop**
  (`api_agent.run_api_agent`), not the original `ClaudeSDKClient` CLI subprocess (the CLI path was
  removed from the SDK). Same prompts/criteria/models/judge panels — only the transport differs.
- **Decomposed:** the shipped `run_simmer_domain` (bounded `relay.complete` calls, single relay judge
  at the inert `JUDGE_COUNT=1/JUDGE_SAMPLES=1` default).

**Cost mechanism (one, shared):** both arms record **accurate per-call tokens** into a
`simmer_sdk.usage.UsageTracker` and are priced by the **same** `PRICING` table (Sonnet $3/$15, Haiku
$0.8/$4 per Mtok). The agentic arm's direct-API loop records every turn via `UsageTracker.record()`
(verified by a Phase-0 spike); the decomposed arm hooks orrery-relay's `on_usage`. No `total_cost_usd`
bridge, no token-undercount asterisk. **Quality** was assessed by an LLM reading both arms' goldens +
specs against the 10 source chunks (not exact-match F1, which is too brittle).

## Cost / time

| Metric | Agentic (`refine()`) | Decomposed (shipped) | Ratio |
|---|---|---|---|
| **Cost (USD)** | **$12.58** | **$0.46** | **27× cheaper** |
| Total tokens | 3,795,544 | 146,601 | 26× fewer |
| Input tokens | 3,695,896 | 126,597 | 29× fewer |
| Output tokens | 99,648 | 20,004 | 5× fewer |
| API calls | 190 | 51 | 3.7× fewer |
| Wall-clock | 1226 s (~20.4 min) | 321 s (~5.4 min) | 3.8× faster |
| Models | all Sonnet (97 golden + 93 spec) | 11 Sonnet + 40 Haiku | — |

**Why the gap is so large:** the agentic arm is **input-token-bound** (3.70M in : 0.10M out — a 37:1
ratio) because the tool-using board judge re-sends accumulated context and re-reads chunks every turn;
**87% of its cost ($10.94) was judging.** The decomposed arm pushes bulk extraction to **Haiku** (40
calls = $0.08) and spends Sonnet only on its ~11 judge/generator/type-discovery calls ($0.38).

## Quality (grounded LLM read vs the 10 source chunks)

> The decomposed golden is **additive** (only the 5 domain-specific types; generic types come from a
> separate general pass), so it is judged on domain-specific entities, not generic coverage.

**Decomposed WINS — the two axes that matter most for this pipeline:**
- **Spec generalizability.** The agentic spec **overfit**: it baked corpus-specific names into its
  *rules* — e.g. a "Hard inference note" that `notes.granola.so` ⇒ extract product `granola`, plus
  rules built around `websim`, `opus clips`, `drop culture`. These fail on unseen docs. The decomposed
  spec states transferable rules and explicitly forbids hardcoding ("apply to ANY document… Do NOT
  hardcode specific names"); corpus tokens appear only as "(e.g., …)" illustrations.
- **Taxonomy usefulness + funding-round coverage.** Decomposed models VC-first-class types and keeps
  the load-bearing deal terms (`$4M on $20M valuation`, `$1.5–2M seed`, `$500k`); the agentic golden
  flattens firms/investors into generic `Person`/`Organization` and **strips the dollar amounts**.
- **Spec usability.** Decomposed spec is 31 tight lines (runnable by Haiku); the agentic spec is 82
  lines, partly dead weight, and is even mislabeled "# Golden Set".

**Decomposed LOSES — one narrow, fixable cost:**
- **`competitor` precision:** 4 bad calls — `panopticon` (a metaphor), `ebay` (a 1998 analogy),
  `matrices` / `websim` (investment *targets*, the inverse of competitors). Agentic typed these more
  safely.
- **Misses:** investor `borthwick`; and it conflated `Cummer Capital` (a fund) with `Cummer
  Corporation` (an operating co) that the source explicitly distinguishes.
- Both are largely addressable with a one-line tightening of the decomposed spec's own `competitor`
  EXCLUDE rule.

(Self-reported judge composites — agentic 7.3/7.5 vs decomposed 7.7/5.7 — are **not** comparable:
different judges, different scales. The decomposed spec phase did show real F1 movement: 0.56 → 0.58 →
0.63.)

## Interpretation

The headline isn't just "decomposed is cheaper" — it's that **the agentic flow's expense correlated
with overfitting, not quality.** Re-reading the corpus on every turn led the agentic generator to
memorize this batch's names into the spec, which is a generalization liability. The decomposed flow's
bounded, single-pass structure produced a more transferable spec for 1/27th the cost.

## Caveats

- **n=1** — one domain, one run per arm. Directional, not significant. Within-arm variance is real.
- **One domain type** (`vc_firms`); other domains may differ (e.g. taxonomy-heavy domains where the
  board's structural ASIs help — see the multi-judge-board validation findings).
- **Transport:** the agentic arm used the SDK's current direct-API tool-loop, not the original CLI
  subprocess (strategy identical; the CLI path no longer exists in the SDK).
- Quality is one LLM's grounded read, not a hand-checked gold standard.

## Reproduction

Experiment code is **scratch**, kept in `DS-scratch/noospheric_agentic_vs_decomposed_simmer/`
(intentionally out of this repo — see "What's committed" below):
- `simmer_domain_agentic.py` — old agentic flow restored from `58498de` + additive
  `result.usage` capture → `cost.json`. (Recoverable in-repo at tag `exp/pre-decomposition-simmer`.)
- Scratch runners (`bakeoff_agentic.py`, `bakeoff_decomposed.py`): load `.env`, copy + pin the DB to N
  chunks, isolate `SPECS_DIR`, run one arm. The decomposed runner monkeypatches `Relay.from_settings`
  to attach an `on_usage` hook → `UsageTracker`.
- Run via `worker/.venv/bin/python` (resolves the usage-capable editable `simmer-sdk`; the vendored
  `worker/simmer-sdk/` Docker copy has no usage tracking and must not be used).

## What's committed vs not

- **Committed (this doc + the design doc):** conclusions, methodology, the numbers, how to reproduce.
- **Not committed:** the resurrected agentic module, the runners, DB copies, raw `cost.json`, goldens,
  specs, per-iteration judgments. They are experiment scratch — kept locally, not in the repo.
