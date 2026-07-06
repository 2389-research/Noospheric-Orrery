# Graph Corrections — the self-healing loop

Canonical reference for how the knowledge graph corrects itself: an agent consuming the
graph flags a problem, an independent model judge advises, a human decides, and — on
approval — the graph is **reversibly** edited. This doc tracks **how each correction
action applies and how it reverses**. Keep it accurate to the shipped code, not aspirational.

**Status (2026-07-06):** propose → judge → display → human approve → reversible apply are
built on `experiment/graph-corrections-intake` (not yet merged). Split, rollback UI,
search-surface threading, and auto-apply are deferred (see bottom).

## The loop

```text
agent uses graph (MCP read tools)
  └─ propose_correction (MCP write) ─▶ graph_issues (status=pending)
       └─ judge (worker job: periodic sweep + manual) ─▶ advisory {verdict, confidence, rationale}
            └─ human reviews (CorrectionsPanel) ─▶ POST /corrections/review/{id}?action=approve|reject
                 └─ approve ─▶ resolve_correction ─▶ apply_* (reversible, logged)   reject ─▶ status only
```

Design history: `docs/superpowers/specs/2026-07-01-graph-self-healing-invalidate-spike-design.md`
and `…/2026-07-02-graph-self-healing-human-reviewed-corrections-design.md`. Judge validation:
`experiments/2026-07-06-graph-self-healing-judge-probe/`. Build plans:
`docs/superpowers/plans/2026-07-06-graph-corrections-{intake,judge,judge-schedule,ui,apply,merge-apply}.md`.

## Data model

- **`graph_issues`** — the proposal queue: what was proposed + the advisory verdict + the human
  decision. Columns: `action`, `target_entity_id/name`, `target_b_entity_id/name` (merge),
  `proposed_type` (retype), `proposed_name` (rename), `rationale`, `proposer`,
  `status` (`pending`|`accepted`|`rejected`), `judge_verdict/judge_confidence/judge_rationale`
  (advisory), `reviewer`, `resolved_at`. A rejected issue never touches the graph.
- **`normalization_log`** (generalized, append-only) — the history + undo substrate + the
  model-vs-human **calibration dataset**. Columns added beyond the original merge ones:
  `action`, `before_value`, `after_value`, `actor`, `reason`, `model_verdict`,
  `model_confidence`, `reviewer`. Never updated after insert.
- **Soft-delete** — nullable `invalid_at` + `invalid_reason` on `entities` **and**
  `relationships`. The *active graph* is `WHERE invalid_at IS NULL`. Nothing on the
  corrections path is ever hard-deleted. `entities.updated_at` is bumped on each edit.

## Surfaces / triggers

| Stage | Surface | Code |
|---|---|---|
| Propose | `propose_correction` MCP tool → `POST /corrections/propose` | `orchestrator/src/mcp_server.py`, `routes/corrections.py`, `pipeline/graph_repair.py:propose_correction` |
| Judge | worker job `judge_corrections`; **periodic sweep** every `JUDGE_SWEEP_INTERVAL_SECONDS` (default 900) **+ manual** `POST /corrections/judge` | `worker/src/jobs/graph_repair.py`, `worker/src/main.py` |
| Review | `CorrectionsPanel` on the pipeline page → `POST /corrections/review/{id}?action=approve\|reject` | `frontend/src/components/corrections-panel.tsx`, `routes/corrections.py`, `pipeline/graph_repair.py:resolve_correction` |
| Reads | `invalid_at IS NULL` threaded through `/graph`, `/entities`, traversal (`graph_ops`) | `routes/graph.py`, `repositories/sqlite_store.py`, `routes/graph_ops.py` |

**Judge contract:** action-aware, adversarial ("try to refute"), source-grounded (gathers the
target's **FULL** source chunks + neighborhood, scoped by `target_entity_id`), **no web search
any tier**, bounded non-agentic relay call (`think:false`; local models stall in agentic loops),
model = `settings.classification_model`. Verdict ∈ `{accept, reject, defer}`. **Advisory only —
it orders/frames the queue, never gates.** Idempotent (only judges `judge_verdict IS NULL`), and
robust: invalid/blank verdicts are left NULL (retryable), each issue judged+committed
independently (no batch poison pill).

## The actions — apply and reverse

All live in `orchestrator/src/pipeline/graph_repair.py`, take an injected `conn`, and (on the
approve path) run inside `resolve_correction`'s **single atomic commit**. Every apply writes one
`normalization_log` row carrying the model verdict + human reviewer.

| Action | What apply changes | Blast radius | How it reverses |
|---|---|---|---|
| **invalidate** | sets `invalid_at` on the node **and its incident edges**; records the affected edge-ids as JSON in the log | node + its own edges (co-occurrence weights of *other* pairs are unaffected) | `rollback_invalidation` clears `invalid_at` on the node + exactly the logged edge-ids |
| **retype** | `UPDATE entities.type`; logs `before`/`after` | the node's `type` field only — zero edge impact | re-apply the logged `before_value` as the type |
| **rename** | `UPDATE entities.canonical_name`; logs `before`/`after` | the node's name only — zero edge impact | re-apply the logged `before_value` as the name |
| **merge** | reattributes the loser's `entity_sources` → survivor; **recomputes** the survivor's 1-hop co-occurrence edges over the combined chunk set (`weight = distinct shared chunks`); aliases the loser name in `merge_map`; **soft-deletes** the loser; snapshots the full before-state (moved source rowids + all incident edge rows + prior `merge_map` alias) in the log | the survivor's 1-hop neighborhood (edges recomputed) | `rollback_merge` reads the log snapshot (survivor via the log's `to_entity_id`, **not** by name), moves sources back, restores the exact pre-merge edge rows, restores the prior `merge_map` alias, clears the loser's `invalid_at` |
| **split** | **not built** — needs mention-level offsets (`entity_sources` is chunk-grained) | — | — |

**Merge specifics.** Survivor = the entity with **more `entity_sources`** (tie → `target_b`).
Why merge is the hard one (vs the naive normalization merge in `embedding_normalizer`): the
co-occurrence `weight` is a *shared-chunk count*, so a naive `UPDATE relationships SET from_entity=…`
double-counts shared chunks and creates duplicate survivor–neighbor rows. Merge therefore drops
both entities' incident edges and **recomputes** them; a chunk where both loser and survivor
co-occur with a neighbor counts **once**. It soft-deletes (never `DELETE`s) the loser so the merge
is reversible.

## Reversibility & the undo ordering constraint

- `rollback_invalidation` and `rollback_merge` exist and round-trip exactly (tested).
  `retype`/`rename` reverse by re-applying the logged `before_value`. **No rollback UI yet** — the
  functions + log are the substrate for a future undo button.
- **⚠️ Ordering constraint (not yet enforced):** `apply_merge` hard-deletes + recomputes the
  survivor's edge rows. If an edge was previously **invalidated** (its id recorded in an
  `invalidate` log) and a later merge touched that neighborhood, the merge deletes that edge row,
  so a subsequent `rollback_invalidation` can no longer find the id. **Rule: undo a merge before
  undoing an invalidation whose edges overlap the merged neighborhood** (roughly, unwind
  corrections LIFO across overlapping neighborhoods). A future rollback UI must respect this or
  guard it.

## Trust ramp (future, not built)

v1 is 100% human-gated. Every human decision is logged next to the model's verdict
(`normalization_log.model_verdict` vs `reviewer`) — that is the calibration dataset that later
justifies automation: human-only → measure per-action agreement + confidence band → auto-apply the
safest sliver (high-confidence `invalidate`) → widen class-by-class. Merge/split never auto-apply
until late; external-knowledge actions (e.g. proper-noun rename) always route to human or a bounded
cloud call. Thresholds are **derived from the log, never hardcoded**.

## Deferred / open

- **Merge apply edge cases**: cross-feature undo ordering (above); merge is otherwise complete.
- **Split**: unbuilt (mention-level provenance).
- **Rollback / undo UI**: functions exist; no button.
- **Search-surface threading**: `invalid_at IS NULL` is **not** yet applied to semantic search or
  the `find_paths`/star-graph seed fetch, so an invalidated entity can still surface there.
- **Auto-apply (trust ramp)**: not built; the log is now collecting the data for it.
- **Local judge**: measure the gemma4 (Ollama) judge-quality drop on the source-grounded subset.
