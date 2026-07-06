# Graph Self-Healing — Invalidate Spike (Design)

**Date:** 2026-07-01 · **Status:** Design (spike) · **Author:** Nomzor
**Branch (intended):** `experiment/graph-self-healing-invalidate-spike`

## Context

Orrery's knowledge graph is *living* — it is continuously added to and consumed by
agents through the MCP read tools. Today corrections flow through exactly one
human-gated path (`normalization_review_queue` + `POST /normalize/review/{id}`), and
the MCP surface is **read-only**. There is no way for a consuming agent to say "this
node looks wrong" and have that reviewed and acted on.

This spike prototypes the smallest end-to-end version of the **usage-driven
self-healing loop** we designed: an agent proposes a correction while using the graph,
an independent reviewer adjudicates it, and — if accepted — the graph is repaired in a
reversible, audited way. See the multi-turn design thread captured in memory
(`usage-driven-self-healing-graph`) and the prerequisite/adjacent work in issue #26
(type ≠ identity) and the multi-judge board.

The spike's real question is **not** "can we wire it up" but **"is the reviewer's
judgement trustworthy?"** — so the deliverable is a measured accept/deny quality
signal, not a shipped feature.

## Goals

- A thin **end-to-end** vertical slice: propose → review → apply → rollback.
- Exactly **one action**: `invalidate` (soft-delete a node that isn't a real/valid entity).
- Measure **verdict validity** with a labeled set that has **both polarities**
  (proposals that *should* be accepted and proposals that *should* be rejected).
- Everything **modular**: each piece is one small unit with a documented interface,
  usable and testable in isolation, and promotable into the real worker loop unchanged.

## Non-goals (explicit YAGNI)

- No other actions (no merge / split / retype / rename / add). `retype` is blocked by #26.
- No live-worker daemon — a **one-shot driver** runs the review pass.
- No UI, no API route.
- No touching production data — runs against a **throwaway copy** of `orrery.db`.
- The multi-judge board knob is *wired but left inert* (`N=1`), not exercised.

## Why `invalidate` is the right first action

Co-occurrence `weight(A,B)` = number of chunks where both A and B appear. Removing a
node X only deletes the pairs `(X, ·)`; every `(A,B)` with neither equal to X is
unchanged. **So `invalidate`'s entire blast radius is X's own incident edges** — no
neighbor reweighting, no re-read, no occurrence partition. (The gnarly 1-hop recompute
lives in *merge/split*, which this spike deliberately avoids.) This makes `invalidate`
the minimal correct mutation and keeps the spike honest about the loop without dragging
in the hard graph-surgery.

## Architecture — five modular units

Each unit has a single purpose, a documented interface, and its own tests. The two
that carry risk (mutation, review) are **pure functions** with no I/O beyond an injected
DB connection, so they are unit-testable without a running server or worker.

### 1. `propose_correction` — MCP write tool
- **Location:** `orchestrator/src/mcp_server.py` (new tool alongside the existing 11).
- **Interface:** `propose_correction(entity: str, action: str = "invalidate", rationale: str) -> {issue_id, status}`.
- **Behavior:** resolve `entity` (name or id) → insert one row into `graph_issues`
  with `status="pending"`. Validation only (action in the allowed set, entity exists).
  It does **not** review or mutate — proposing is frictionless and always succeeds.
- **The "look at things" half** is the *existing* read tools (`get_entity`,
  `get_neighborhood`); no new read tool is needed.
- **Depends on:** the store / DB connection only.

### 2. `graph_issues` + soft-deprecate columns — data model
- **Location:** `orchestrator/src/db.py` (+ mirror in `worker/src/db.py`, per the
  "identical schema" convention).
- **New table `graph_issues`:**
  `id, target_entity_id, target_entity_name, action, rationale, proposer,
   status (pending|accepted|rejected|quarantined), confidence REAL, judge_rationale TEXT,
   created_at`.
  Coalescing is a query, not a schema feature: review selects `WHERE target_entity_id = ?`
  so multiple flags on one node are handled together and their **count is the strength
  signal**.
- **Soft-deprecate (reversibility substrate):** add nullable `invalid_at TIMESTAMP` and
  `invalid_reason TEXT` to **`entities`** and **`relationships`**. The "active graph" is
  `WHERE invalid_at IS NULL`. Nothing is ever hard-deleted. (Migrations via the existing
  `PRAGMA table_info` + `ALTER TABLE` pattern in `init_db`.)
- **Audit:** verdicts + applications recorded (verdict/confidence/rationale on the issue
  row; an application leaves the `invalid_at` trail, which is itself the audit + undo).

### 3. `judge_correction()` — independent reviewer
- **Location:** new `worker/src/jobs/graph_repair.py`.
- **Interface:** `judge_correction(conn, issue) -> {verdict: "accept"|"reject", confidence: float, rationale: str}`.
- **Behavior:** gather evidence — the entity, its **source chunks** (via
  `entity_sources → chunks.text`), and its neighborhood — then ask the model, in an
  **adversarial "try to refute this proposal"** framing, whether the invalidation is
  justified *by the source text*. Grounded in evidence, not vibes (the ODKE+/KGValidator
  lesson). Uses `relay.complete` with `think:false`, mirroring `simmer_core`'s
  bounded non-agentic calls.
- **Board-ready but inert:** structured so N independent verifiers could vote, defaulted
  to `N=1`. No board behavior exercised in the spike.
- **Depends on:** `orrery_relay.Relay`, a read-only DB connection.

### 4. `apply_invalidation()` / `rollback_invalidation()` — mutation (pure, reversible)
- **Location:** `worker/src/jobs/graph_repair.py`.
- **Interface:**
  `apply_invalidation(conn, entity_id, reason) -> {edges_invalidated: int}` and
  `rollback_invalidation(conn, entity_id) -> {edges_restored: int}`.
- **Behavior:** `apply` sets `invalid_at`/`invalid_reason` on the entity **and** on its
  incident `relationships` rows (the entire blast radius, per the analysis above).
  `rollback` clears exactly those flags. Round-trips exactly (invariant, tested).
- **Depends on:** DB connection only. No LLM, no network.

### 5. Eval driver + harness — the deliverable
- **Location:** scratch script (kept in `DS-scratch/`, per the experiment-recording
  convention; not committed to this repo). A thin driver that ties the real modules
  together one-shot.
- **Behavior:**
  1. Copy `~/orrery-data/orrery.db` to a scratch path (isolation).
  2. Seed `graph_issues` with the **labeled** proposal set (below) via **direct insert**
     (keeps the eval independent of the MCP tool's correctness; exercising the tool
     end-to-end is a separate one-off integration check).
  3. Run `judge_correction()` over all pending issues; write verdict + confidence.
  4. Apply gate: `accept` high-confidence → `apply_invalidation`; low → `quarantine`.
  5. Report **raw verdict-vs-label agreement first** (independent of the confidence gate,
     so a mis-set threshold can't mask judge quality), then the **confusion matrix** vs
     labels; apply the accepted set, show the before/after graph diff, then `rollback` and
     show it restores the active-graph state (entity + incident edges exactly as before).

## Labeled eval set (both polarities)

Drawn from the agentic-vs-decomposed VC run (`business/venture_capital/vc_firms`):
- **should-ACCEPT invalidate:** `panopticon` (a metaphor), `ebay` (a 1998 analogy),
  `matrices` / `websim` (investment *targets* mistyped as competitors).
- **should-REJECT invalidate (negative controls):** `Anthropic`, a real VC firm, a real
  funding amount (`$4M on $20M valuation`). A proposal to invalidate these is *wrong*.

Reporting **both** false-accept (dangerous: judge greenlights destroying a real entity)
and false-reject rates is the whole point — a judge that rubber-stamps every
`invalidate` would score perfectly on the ACCEPT set and destroy the graph. The negative
controls are what expose that.

## Data flow

```
agent reads graph (existing MCP read tools)
  └─ propose_correction ──▶ graph_issues (pending)
                              └─ driver: group by target_entity_id
                                   └─ judge_correction() ─▶ {verdict, confidence}
                                        └─ gate: accept(high) / reject / quarantine(low)
                                             └─ if accept: apply_invalidation()  (reversible)
                                                  └─ audit trail = invalid_at
```

The same functions later drop into a real `graph_repair` job handler (worker poll loop +
`runner.py` dispatch) with no interface change — that promotion is out of scope here.

## Testing

- **`apply_invalidation` / `rollback_invalidation`:** round-trip invariant on a fixture
  DB — after apply+rollback the entity and its edges are exactly as before; edge counts
  match; only incident edges touched.
- **`graph_issues` insert:** `propose_correction` writes a well-formed pending row;
  unknown entity / bad action rejected.
- **`judge_correction`:** smoke test with a stubbed relay (deterministic response) so the
  gating logic is tested without a live model.
- Fixtures use `tmp_path` SQLite isolation, matching the existing test conventions.

## Modularity contract (the "nice modular way" the user asked for)

- Five units, five files/functions, each with the interface stated above.
- Mutation and review are **pure functions taking an injected connection** — no globals,
  no server, no worker daemon required to run or test them.
- The DB schema changes are additive and migration-guarded.
- Only the MCP tool and the schema are "real" edits to shipped files; review, mutation,
  and eval live in a new `graph_repair` module + a scratch driver, so the blast radius on
  the codebase is small and the spike is easy to delete or promote wholesale.

## Open questions / deferred

- Chunk-grained provenance can't cleanly separate two senses sharing a chunk — irrelevant
  for `invalidate`, becomes real for `split` (would need mention-level offsets). Deferred.
- Confidence-gate thresholds (accept / quarantine cutoffs) are guesses until the eval runs;
  the harness reports calibration so we can set them from data.
- Quarantined issues have **no consumer** in the spike — they are parked (not applied,
  not rejected, not re-surfaced). Deliberate: no quarantine-handling subsystem is in scope.
- The blast-radius claim rests on `cooccurrence.py` computing `weight` as a pure per-pair
  chunk count (no degree/total-chunk normalization). Confirm against the actual source
  during planning before relying on "no neighbor reweighting."
- Promotion to the live worker + additional actions (merge/split/retype) gated on this
  spike showing the judge is trustworthy, and on #26 for retype.
