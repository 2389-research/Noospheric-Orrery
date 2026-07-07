# Graph Self-Healing — Human-Reviewed Corrections (v1 Design)

**Date:** 2026-07-02 · **Status:** Design · **Author:** Nomzor
**Branch (intended):** `experiment/graph-self-healing-corrections`
**Supersedes:** `2026-07-01-graph-self-healing-invalidate-spike-design.md` (the invalidate-only spike — its
blast-radius analysis and modular-unit framing are carried forward here; the scope is now broader and
the apply-gate is human review, not confidence-gated auto-apply).

## Context

Orrery's knowledge graph is *living* — continuously added to and consumed by agents through the MCP read
tools. Today corrections flow through exactly one human-gated path (`normalization_review_queue` +
`POST /normalize/review/{id}`), and the MCP surface is **read-only**. A consuming agent that notices "this
node looks wrong" has no way to say so.

This design ships the smallest genuinely-useful version of the **usage-driven self-healing loop**
(design thread in memory `usage-driven-self-healing-graph`): an agent proposes a correction while using
the graph, an **independent model judge advises**, and a **human makes the final call**. Nothing
auto-applies in v1. The model does triage; the human decides. Crucially, every human decision recorded
next to the model's verdict becomes the **calibration dataset** that later justifies automation — so
human-review-first is not a fallback from automation, it is what earns it.

## What ships in v1 (scope)

1. **Proposal** — a new MCP **write** tool (`propose_correction`) lets a consuming agent file a structured
   issue. Frictionless: proposing always succeeds.
2. **Advisory judge** — a worker job runs an **action-aware, source-grounded** judge over pending issues
   and writes `{verdict, confidence, rationale}` onto each as **advisory metadata** (never a gate).
3. **Human review queue** — issues surface in the Pipeline page (cloning the normalization vertical),
   sorted/annotated by the model's take. Human clicks **Approve / Reject** (and optionally edits the
   proposed value first).
4. **Reversible apply** — on Approve, the mutation is applied via a soft-delete flag (`invalid_at`) and
   recorded append-only in a generalized `normalization_log`. Undo is trivial.

Four actions are detected + judged: **invalidate · merge · retype · rename**. Apply-on-approve is wired
for the cheap/reversible ones (invalidate, retype, rename); **merge apply is deferred** (heavy 1-hop
recompute) — merge proposals are still detected, judged, and human-reviewed, just not auto-executed.
**Split is deferred entirely** (needs mention-level provenance we don't store).

## Non-goals (explicit YAGNI)

- **No auto-apply of anything.** The confidence-gate / quarantine machinery from the spike is deferred to
  the trust ramp (below), not built now.
- **No bi-temporal / versioned nodes.** History is a single append-only log (level 1) + one soft-delete
  flag. (Decision 2026-07-02.)
- **No web search / internet access in the judge — ever, any tier.** ~13/14 probe verdicts were reachable
  from source evidence alone (see Judge validation). External-knowledge cases escalate to a bounded cloud
  model call, never an agentic web loop.
- **No split action.** No merge *apply* (detect + review only).
- **No touching production data during development** — runs against a throwaway copy of `orrery.db`.

## The four actions & blast radius (carried from the spike)

Co-occurrence `weight(A,B)` = number of chunks where both A and B appear (confirmed: `relationships` holds
only `co_occurs` edges with weight = shared-chunk count). Removing node X only deletes pairs `(X, ·)`;
every `(A,B)` with neither = X is unchanged. So:

- **invalidate** — blast radius = X's own incident edges. No neighbor reweighting, no re-read. Trivial + reversible → apply in v1.
- **retype** — flips the `type` field. Zero edge impact, fully reversible → apply in v1.
- **rename** — changes `canonical_name`. Zero edge impact, reversible → apply in v1.
- **merge** — heavy: reattribute `entity_sources`, redirect via `merge_map`, recompute incident edges. Detect + review only in v1.
- **split** — hardest: needs mention-level offsets (`entity_sources` is chunk-grained). Deferred.

## Judge validation — the 14-case probe (2026-07-02)

Before building `judge_correction()`, we ran live Claude subagents as blind, adversarial judges over 14
real proposals drawn from the VC domain (`business/venture_capital/vc_firms`), both polarities, scored
against hidden labels. Each judge saw only one case's evidence pack (entity type + source chunks +
neighborhood) and the proposal — not the label, not the other cases.

**Results:** 11/14 matched hand-labels raw, but the analysis is the point:
- **0 false-accepts across 5 negative controls.** Every proposal that would have destroyed/corrupted a
  real entity (invalidate `matrices`/`true ventures`, merge a firm into its founder, retype a person to
  an org, misspell a correct name) was **rejected at 0.93–0.98 confidence.** This is the failure mode that
  matters for a mutating graph.
- **All 3 disagreements were conservative (declined to mutate), and 2 were the judge out-reasoning the
  labels** — it caught that "Commer Capital" is a deliberately-named *new* entity (not a typo of "Cummer
  Capital"), and that a `borthwick→Person` retype should be a MERGE because a `john borthwick` node already
  exists. The third (panopticon) was an **evidence-gap**, not a reasoning error — the disambiguating
  sentence lived in a co-located entity's chunk the pack didn't include.
- **Calibration works.** The two genuinely ambiguous accepts (`ebay`, `reed hoffman`) scored 0.68 vs
  0.92–0.98 for clean cases — a ~0.85 band cleanly separates confident from uncertain.

**Two lessons baked into this design:**
1. **Evidence-gathering is co-equal with judging.** The one real miss was caused by a truncated chunk set
   → `judge_correction()` must pull the entity's **full** source chunks, not a sample.
2. **The judge wants a richer verdict than accept/reject** → include a **DEFER / suggest-alternative-action**
   verdict (matches de Martim et al. REVIEW+DEFER in the design memory).

Cost: ~350k subagent tokens total, ~15s median/case — cheap enough to keep as a regression harness.

## Judge design

- **Action-aware.** One judge, four framings — invalidate ("is this NOT a real entity of its kind?"), merge
  ("do these denote the SAME referent? reject firm-vs-founder"), retype ("does source usage show current
  type wrong AND proposed right?"), rename ("is current name a garbled form of a real referent?").
- **Adversarial.** Default stance skeptical — try to refute the proposal.
- **Source-grounded, no internet.** Judge from the evidence pack + widely-known facts only. Classify each
  action's dependency: **source/graph-grounded** (local-viable on gemma4) vs **external-knowledge**
  (rename-to-canonical-proper-noun) — the latter routes to human or a bounded cloud-model call.
- **Local/cloud tiers.** Same evidence pack for both, so the local model gets the same *inputs*; the gap is
  reasoning quality, not knowledge access. (Open: measure gemma4 drop on the bucket-A subset.)
- **Bounded non-agentic relay call** with `think:false`, mirroring `simmer_core` — no agentic loop (gemma4 stalls).

## Change tracking & node history (Decision 2026-07-02: level-1 log + soft-delete flag "A")

We use an **append-only change log** as the history mechanism, **reusing/generalizing `normalization_log`**
rather than a new table. No versioning.

**1. Generalize `normalization_log`** (additive, migration-guarded via the `PRAGMA table_info`+`ALTER TABLE`
pattern in `init_db`; the 188 existing merge rows stay valid):
```
+ action           TEXT   -- 'merge' | 'invalidate' | 'retype' | 'rename'   (backfill existing → 'merge')
+ before_value     TEXT   -- old type / old name / null
+ after_value      TEXT   -- new type / new name / null
+ actor            TEXT   -- proposing agent id / 'human'
+ reason           TEXT   -- proposer or reviewer rationale
+ model_verdict    TEXT   -- advisory: accept|reject|defer
+ model_confidence REAL   -- advisory
+ reviewer         TEXT   -- who approved
```
Existing merge columns (`from_*`, `to_*`, `method`, `similarity`) stay NULL for non-merge actions. This one
table is the **node-history mechanism** AND the model-vs-human **calibration dataset**. Append-only — never
updated after insert.

**2. `entities.updated_at`** — nullable, backfilled from `created_at`, set on each applied edit. (Add to
`relationships` only if we start editing edges directly.)

**3. Soft-delete = option A.** Add nullable **`invalid_at TIMESTAMP` + `invalid_reason TEXT`** to `entities`
and `relationships`. "Active graph" = `WHERE invalid_at IS NULL`. `invalidate` sets it (on the node + its
incident edges); undo clears it. This is *not* bi-temporal — it is one current-state marker so reads stay a
simple filter instead of folding the event log. **Cost:** thread `WHERE invalid_at IS NULL` through the read
paths (`/graph`, `/entities`, reader, cooccurrence) — mechanical but must be complete.

**Two tables, two jobs:** `graph_issues` = proposals + verdict + human decision (the queue);
`normalization_log` = what actually changed, with before/after for undo (the history). A rejected issue
never touches the log; an approved one writes exactly one log row + applies the mutation.

## Human review queue + trust ramp

v1 is 100% human-gated. The model's `{verdict, confidence, rationale}` are advisory annotations that
**order and frame** the queue (high-confidence-accept → top, 1-click approve; low-confidence → "needs
judgment"; high-confidence-reject → "no action recommended", dismissable; DEFER → "unsure which action").

| Phase | Who decides | What graduates to auto | Threshold source |
|-------|-------------|------------------------|------------------|
| **0 — ship now** | 100% human | nothing | — (collecting decisions) |
| **1 — measure** | 100% human | nothing | compute model-vs-human agreement per action class + confidence band on the log |
| **2 — first automation** | model auto-applies the safest sliver; human handles rest | high-confidence `invalidate` only, where it hits the bar AND zero false-accepts | thresholds derived from Phase-1 data, not guessed |
| **3 — widen** | expand class-by-class; humans audit a sample + own the low-confidence tail | add retype/rename as each clears the bar | rolling recalibration |

Invariants: **merge/split never auto-apply** until very late; **external-knowledge actions always route to
human or cloud-escalation**; thresholds are **derived, never hardcoded**; a spike in human-overrides for a
class pulls it back to manual.

## UI surfacing — clone the normalization vertical

The normalization feature is a clean 5-layer template; each layer has a direct mirror:

| Layer | Normalization (existing) | Corrections (to add) |
|-------|--------------------------|----------------------|
| Schema | `normalization_review_queue`, `normalization_log` (`orchestrator/src/db.py:119`) | `graph_issues` + generalized `normalization_log` + `invalid_at`/`updated_at` cols |
| Logic | `pipeline/embedding_normalizer.py`: `get_review_queue`, `resolve_review` | `pipeline/graph_repair.py`: `get_correction_queue`, `resolve_correction`, `apply_invalidation`/`rollback` (pure fns, injected conn) |
| Route | `routes/normalize.py` (51 lines) | `routes/corrections.py`: `GET /corrections/summary`, `GET /corrections/review`, `POST /corrections/review/{id}?action=approve\|reject` |
| API client | `frontend/src/lib/api.ts:63-73` | `getCorrectionsSummary`, `getCorrectionQueue`, `resolveCorrection(id, action)` |
| UI | `components/normalization-panel.tsx` @ `pipeline/page.tsx:142` | `components/corrections-panel.tsx` |

**Placement:** `pipeline/page.tsx:136` is a 2-col grid (Domains | Normalization). To limit bloat, mount
`<CorrectionsPanel />` as a **full-width row below the grid** ("the graph's self-maintenance queue" beneath
the build controls) rather than a cramped 3rd column.

**Approve = the DB edit.** Mirrors `resolve_review` (`normalize.py:42`), which already mutates the graph on
human click. Approve → `apply_invalidation()`/retype/rename (reversible write + log row); Reject → status
only. "Edit" affordance = human tweaks the proposed value (e.g. rename target) via one extra field in the
resolve payload.

⚠️ **Implementation gate:** `frontend/AGENTS.md` warns this Next.js has breaking changes vs. training data —
read `node_modules/next/dist/docs/` before writing the panel/page (routing & params conventions especially).

## Architecture — modular units

Mutation and review are **pure functions taking an injected DB connection** — no server/worker needed to
run or test them; promotable into a real `graph_repair` worker job unchanged.

1. `propose_correction` — MCP write tool (`orchestrator/src/mcp_server.py`): resolve entity → insert
   pending `graph_issues` row. Validation only.
2. `graph_issues` table + generalized `normalization_log` + soft-delete cols — data model (`db.py` + mirror in `worker/src/db.py`).
3. `judge_correction(conn, issue) -> {verdict, confidence, rationale}` — action-aware source-grounded judge
   (`worker/src/jobs/graph_repair.py`). **Gathers the entity's FULL source chunks** (the probe lesson).
   Board-ready but inert (`N=1`).
4. `apply_invalidation(conn, entity_id, reason)` / `rollback_invalidation(conn, entity_id)` — pure,
   reversible; sets/clears `invalid_at` on node + incident edges; writes the log row. Round-trips exactly (tested).
5. Review surface — orchestrator route + `CorrectionsPanel`, cloning normalization.

## Labeled eval set (5 issue types, both polarities) — real entities

Grounded in `~/orrery-data/orrery.db`, VC domain. ACCEPT = agent should flag; REJECT = flagging is wrong.

- **invalidate** — ✅ `panopticon` (metaphor), `ozymandias` (Watchmen analogy); ⚠️ `ebay` (1998 analogy,
  low-conf); ⛔ `matrices`, `true ventures` (real — negative controls).
- **merge** — ✅ `web sim`↔`websim` (spacing), `lvmh`↔`louis vuitton moet hennessy` (acronym); ⚠️
  `commer capital`↔`cummer capital` (ambiguous — probe judged distinct); ⛔ `cummer capital`↔`russell cummer`
  (firm vs founder).
- **retype** — ✅ `series a` Event→FundingRound; ⚠️ `borthwick` Org→Person (probe: should be MERGE); ⛔
  `harper reed` Person→Org.
- **rename** — ✅ `reed hoffman`→"Reid Hoffman" (external-knowledge, low-conf); ⛔ `harper reed`→"Harper Read".
- **split** — no clean natural instance in this graph; deferred.

Reporting **both** false-accept (dangerous) and false-reject rates is the point; negative controls expose a
rubber-stamp judge.

## Testing

- `apply_invalidation`/`rollback_invalidation`: round-trip invariant on a fixture DB — after apply+rollback
  the entity + incident edges are exactly as before; only incident edges touched.
- `graph_issues` insert: `propose_correction` writes a well-formed pending row; unknown entity / bad action rejected.
- `normalization_log` generalization: existing merge rows still parse; new-action rows carry before/after.
- `judge_correction`: smoke test with a stubbed relay (deterministic) so gating logic is testable without a live model.
- `tmp_path` SQLite isolation, per existing conventions.

## Open questions / deferred

- **Measure gemma4 (local) judge drop** on the source-grounded (bucket-A) subset — the actual test of the
  no-internet claim. Same packs, same prompt, local model via relay/ollama.
- Confidence-gate thresholds: derived from the Phase-1 review log, not guessed (v1 collects the data).
- merge apply (1-hop recompute), split (mention-level offsets), retype-as-identity-split — gated on #26.
- `graph_issues` proposal coalescing (repeat flags on one node = stronger signal) — a query, not schema; wire in when volume warrants.
