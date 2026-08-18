# Per-Source Silos + Provenance — Design

**Issues:** closes #50 (per-source silos), folds in and closes #79 (provenance for agent-generated docs).
**Date:** 2026-08-18
**Status:** design — for review before an implementation plan.

## 1. Problem

A noosphere is one blended graph. Two failures emerge as we ingest more, and more varied, corpora into a single noosphere:

1. **Cross-corpus merge pollution (#50).** Normalization matches entities by name/embedding across the *whole* noosphere. Ingest a mythology vault and chemistry notes together and "Mercury" (the god) and "Mercury" (the element) collapse into one node, uninvited.

2. **Provenance blindness / contamination (#79).** As agent-generated docs (retros, best-practice reports) enter the graph alongside neutral code summaries, a consuming agent can't tell "what the code *does*" from "what another agent *thinks*." Worse, agents start learning off prior agents' claims — a drift/feedback loop with no ground-truth anchor.

Both are the same shape: **the graph loses track of where a document came from, and treats everything as one undifferentiated pool.** The fix for both is to preserve that origin and let normalization + reads respect it.

## 2. Core model — the *silo*

**A silo is a source of documents, identified by that source's own stable UUID, assigned by the ingestion pipeline — and only when a real source exists.**

- **Vault / git org / repo / tracker corpus** → each has its **own stable UUID** (re-scanning the same vault → same silo; a silo is durable, not per-run).
- **One-off / drag-in uploads** → **no silo** (`silo_id = NULL`). Orrery never invents a silo it can't know.
- **Batch/run identity is separate** — an ingestion *run* has its own id (the existing `jobs` row / `entity_sources.job_id`), used for tracking, **not** as the silo key. (A batch UUID as the silo would fragment a re-scanned vault into a new silo each run — explicitly rejected.)

This maps almost 1:1 onto what #78 already built: `documents.source_id → watched_sources` is effectively the silo key, and a one-off upload already has `source_id = NULL`. The work is mostly **threading this through normalization + reads + viz**, not new identity infrastructure. (See §5 for reconciling `source_id` vs `collection_id` as silo keys.)

### Two decisions the model rests on
1. **Silo = the scoping unit** (which candidates may normalize together).
2. **Silo carries a `kind`/nature** (the provenance axis) — `neutral_summary`, `human_vault`, `agent_report`, … — which is *not a second axis to tag per-doc*, but an attribute of the silo. This is the surviving substance of #79: provenance is a property of the source, set at ingestion, because the ingestion *flow* determines both which corpus a doc is and what epistemic kind it is.

## 3. The normalization rule (the heart of it)

- **Within a silo** (same `silo_id`) → **auto-normalize, exactly as today.** One coherent corpus is what normalization is good at; low risk.
- **Unsiloed docs** (`silo_id = NULL`) → **normalize among themselves, exactly as Orrery does today.** No synthetic catch-all silo — null is null. (A noosphere that never configures a source sees *zero* behavior change.)
- **Across silos** (or silo ↔ unsiloed) → **never auto-merge.** A likely cross-silo duplicate (same name / high embedding similarity) is **proposed** into the human-gated corrections flow (`graph_issues`), reversible, human decides.

**Design stance:** Orrery makes only the *safe* call automatically (within-silo) and never the *risky* one (cross-boundary), which it routes to a human through machinery that already exists and reverses cleanly. This is the resolution to "should Orrery decide whether to normalize?" — within-corpus yes, cross-corpus no.

### 3.1 How scoping actually works (the hard part — #50's "design pass before code")

Silo lives on **documents**; normalization operates on **entities**. An entity's effective silo is the silo(s) of its source documents (`entity_sources → documents.silo_id`). **Multi-silo entities are real and expected:** after a human-approved cross-silo merge, the survivor legitimately has sources in two silos. The rule: **a multi-silo entity participates in the candidate set of *every* silo it has a source in** (so re-ingest from either silo re-attaches to it); **cross-silo *auto*-merge stays barred regardless.** `entities` rows carry no silo, so every scoping query joins `entity_sources → documents.silo_id`, and needs an index on `documents.silo_id`.

**FOUR auto-merge paths must become silo-aware — and within each, *every* sub-check that can fuse two names, not just the embedding query.** These were mis-inventoried in an earlier draft; grounded here:

1. **`worker/src/jobs/upsert_document.py::extract_document_entities` (the PRIMARY inline path, lines ~96-105).** This is the hand-rolled inline dedup for **every repo / tracker / watched-vault ingest — i.e. exactly the corpora that become silos.** It runs at extraction time, *before* batch normalization. Both of its lookups are currently global and must be silo-scoped:
   - the `merge_map` short-circuit (`SELECT to_entity_id FROM merge_map WHERE from_name = ?`) — see the merge_map note below;
   - the exact `SELECT id FROM entities WHERE canonical_name = ? AND type = ?` — must additionally require a source in the current silo.
   *If this path is left global, "Mercury" auto-merges across two repo silos at extraction time and #50 fails for the sources it matters for most. This is the heart of the fix.*
2. **`orchestrator/src/pipeline/normalizer.py::normalize_entity`** — the inline dedup for **loose single-doc uploads only** (called from `routes/ingest.py`), i.e. the `silo_id IS NULL` pool. Same scoping for consistency (mostly a no-op since null-pool behaviour is unchanged).
3. **`worker/src/normalizer.py::run_batch_normalization`** (faiss). Two auto-merge stages, both currently global, both must be silo-scoped: **Tier-1 plural collapse** (`agents`→`agent` via a global `all_names` set / `get_by_name`) *and* the faiss candidate search. The faiss index is **ephemeral, built per-type in memory each run** — not a persistent global index — so partitioning is just widening the grouping key from `type` to **`(type, silo)`** and restricting the query set. Cheap.
4. **`orchestrator/src/pipeline/embedding_normalizer.py::run_batch_normalization`** — a **different algorithm** from #3 (an O(n²) all-pairs nested loop, no faiss, no incremental gate). Its plural collapse + all-pairs comparison must be silo-scoped independently.

**The two batch normalizers are NOT a mirror.** They are already different implementations, and `test_schema_mirror` only diffs `db.py` + `classifier.py` DDL — it does **not** cover the normalizers. So each must be silo-scoped *separately* and get its **own** silo-scoping test. (Decision for review: consolidate the two batch normalizers first, or scope both in place.)

**merge_map is a global alias table** (`from_name` PRIMARY KEY, no silo) — the biggest leak. A `merge_map` hit currently short-circuits straight onto the aliased entity regardless of silo, never touching the candidate `SELECT` we're scoping. Scoping rule: **honor a `merge_map` hit only if the target entity has a source in the current silo; otherwise treat the mention as new (do not follow the alias).** (Alternative for review: key merge_map by `(silo_id, from_name)`. Cleaner long-term but a schema + backfill change.)

**Cross-silo detection → proposal (by entity id).** When any batch stage finds a high-similarity pair straddling silos (or silo ↔ null), it does **not** merge — it files a `graph_issues` proposal via `graph_repair.propose_correction` (`action="merge"`, `target_b`, similarity as rationale), **keyed on entity id, not name** (names are ambiguous once they legally coexist across silos). `resolve_correction → apply_merge → rollback_merge` round-trips cleanly (verified), so an approved cross-silo merge and its undo stay consistent. **Note the LIFO undo ordering constraint** in `docs/graph-corrections.md` (undo a merge before an overlapping invalidation; "not yet enforced") — cross-silo merges add overlapping-neighborhood merges, making that unenforced constraint more load-bearing; worth enforcing or at least flagging.

**Two review queues, kept apart:** within-silo review-band pairs (~0.70–0.85) continue to `normalization_review_queue` exactly as today (it has no silo awareness and no merge-snapshot/rollback — fine, it never sees cross-silo pairs). **Any cross-silo pair — auto-band *or* review-band — goes to `graph_issues` only.**

**Open scoping decision (for review):** is within-silo scope *hard* ("never auto-merge across silo, full stop") or a per-noosphere policy knob? Default proposal: **hard**, cross-silo only via corrections. No config knob in v1 (YAGNI).

## 4. Provenance `kind` (the #79 remnant)

Each silo has a **`kind`** — a small, closed vocabulary. Candidate set (final list is a review decision):

| `kind` | Meaning | Default `emits_cooccurrence` | Agent trust signal |
|---|---|---|---|
| `neutral_summary` | Map of territory, attestable vs `source_path` (codesum/tracksum) | leaf: yes / rollup: no (existing gate) | high — "what the code does" |
| `human_vault` | Primary human notes (Obsidian, uploads under a vault) | yes | medium — human-authored |
| `agent_report` | Derived agent claims — retros, best-practice sweeps | **gated/down-weighted** | low — "what an agent thinks" |
| `human_reviewed` | An `agent_report` a human vetted | yes | high |

The `kind` drives two things and is **read-exposed** (see §6):
- **Co-occurrence emission** — an `agent_report` silo defaults to gated so opinion docs don't reshape shared edge weights. **This must be a silo-level attribute, NOT the existing `document_collections.emits_cooccurrence` column** — that column lives on a `document_collections` membership row, which a watched **vault** silo never creates (`scan_source.py` vault path calls `upsert_document(collection_id=None)`), and `recompute_cooccurrence` treats a doc with no membership row as *emitting by default* (`COALESCE(...,1)=1`). So the lever is unreachable for exactly the non-collection silos §4 most wants to gate. Design: put an `emits_cooccurrence` default on the **silo row** and have `recompute_cooccurrence` also consult it via `documents.silo_id → silo.emits_cooccurrence` (the per-membership column stays as a finer per-doc override where it exists, e.g. a repo's root/rollup summaries).
- **Agent trust** — surfaced in reads so a consuming agent can weight or disbelieve a node's provenance.

`kind` is **not** used for normalization scoping — scoping is by silo *id* (§3). Two `neutral_summary` repos are still different silos and don't auto-merge. `kind` is metadata about the silo, for emission + trust, not a scoping key.

## 5. Data model

- **`documents.silo_id`** — the silo key, resolved at ingest with an **explicit precedence** (the earlier "source_id XOR collection_id" dichotomy was wrong — a *watched repo* produces BOTH a `watched_sources` row *and* a `collections` row, different UUIDs, on the same document):
  - **`source_id` wins when present** (the collection is derived from and keyed on the watched source), else
  - **`collection_id`** (this makes a **one-shot `POST /ingest/repo`/tracker ingest a silo too** — it has a durable `collection_id` even with no watched source), else
  - **`NULL`** — and null is *only* the loose `POST /ingest` / `/ingest/text` document upload. So "one-off = null" means *ad-hoc uploads*, not one-shot repo/tracker ingests (those are silos).
  Decision for review: a single materialized `silo_id` column populated at ingest (proposed — one indexed column to scope on), vs a computed view over `source_id`/`collection_id` (no migration but every scoping query re-derives the precedence).
- **Silo registry + `kind`** — silos need a home that carries `kind`. `collections.kind` already exists (`git_repo`/`tracker_run`); `watched_sources` needs a `kind` too. Proposal: a per-silo `kind` attribute on the silo's owning row (watched_sources + collections), with a small migration, OR a thin unified `silos` table. (Decision for review.)
- **No change to `entities`/`entity_sources`** — an entity's silo is derived through `entity_sources → documents.silo_id`. Indexing: normalization candidate queries now join on `documents.silo_id`, so it needs an index.

## 6. Reads, MCP, and viz (the #79 exposure half)

Provenance is worthless unless it rides along in what agents read. Surface **silo + kind** in:
- **`GET /entities/{id}` / `get_entity`** — each source annotated with its silo + kind.
- **`search_knowledge_graph`, `get_neighborhood`, `get_subgraph`** — nodes carry their silo/kind (esp. via the MCP tools shipped in #48, the primary agent read path).
- **`GET /graph` snapshot** — nodes tagged with silo + kind; viz gains a **filter control** (show one silo, all, or by kind), satisfying #50's "filter graph/entities/viz by source."
- **Document reads** — the doc's silo + kind.

## 7. Acceptance criteria (mapped to the issues)

**#50:**
- Ingest two sources → the graph is **filterable per source** (viz + query). ✓ §6
- Identical entity names in different silos **stay distinct** (no auto-merge). ✓ §3
- A **deliberate cross-silo merge via corrections** still works **and reverses cleanly**. ✓ §3.1 (reuses `graph_repair` + `rollback_merge`)

**#79:**
- **Provenance vocabulary defined** — the `kind` set + default `emits_cooccurrence` per kind. ✓ §4
- **Provenance exposed in the read layer** — `get_entity`/search/neighborhood/snapshot/doc reads surface `kind`. ✓ §6

## 8. Testing

Cover **all four auto-merge paths** from §3.1, plus the two leaks (merge_map, plural collapse) — a test that only checks the faiss candidate query would pass while the real bugs remain:

- **Primary inline path (the #50 crux):** two repo/vault silos ingested through `extract_document_entities`, both mentioning "Mercury" → two distinct entities, not one. Same name *within* one silo → one entity.
- **Loose path:** `normalize_entity` on two null-silo docs still merges (regression: today's behaviour unchanged).
- **merge_map leak:** an alias created in silo A does **not** short-circuit a same-name mention from silo B onto A's entity.
- **Plural-collapse leak:** `agents`(silo A) and `agent`(silo B) do **not** auto-collapse; within one silo they do.
- **Both batch normalizers, separately:** `worker/src/normalizer.py` (faiss) and `orchestrator/src/pipeline/embedding_normalizer.py` (O(n²)) each keep cross-silo names distinct — separate tests, since they are separate algorithms (`test_schema_mirror` does **not** cover them).
- **Cross-silo proposal + reversal:** a high-similarity cross-silo pair produces a `graph_issues` row (not a merge), by **entity id**; approving it merges and `rollback_merge` reverses it.
- **Emission:** an `agent_report` **vault** silo's docs do **not** emit co-occurrence edges by default — specifically exercising the non-`document_collections` path (B6), since that's the one the old lever missed.
- **Read exposure:** `get_entity` / graph snapshot / MCP reads include silo + kind.

## 9. Out of scope / phasing

- **Phase 1 (this spec's core):** `silo_id` model, silo-scoped normalization (all three call sites), cross-silo → proposal, tests. Delivers #50's substance.
- **Phase 2:** the `kind` vocabulary + `emits_cooccurrence`-per-kind + read/viz exposure. Delivers #79. Can ship as a follow-up PR on the same model.
- **Not now:** a per-noosphere scoping-policy knob; per-doc provenance sub-tagging within a silo (the whole point is provenance = silo, not per-doc); merging two vaults into one silo (they stay distinct; cross-silo merge is per-entity via corrections).

## 10. Open decisions for review
1. **`silo_id` column** — one unified column populated at ingest, vs a computed view over `source_id`/`collection_id`?
2. **Silo `kind` home** — attribute on `watched_sources`+`collections`, vs a thin unified `silos` table?
3. **Scoping hardness** — hard "never auto-merge cross-silo" (proposed), vs a per-noosphere policy knob?
4. **`kind` vocabulary** — the 4 above, or the minimal `neutral` vs `claim`?
5. **Phasing** — ship #50 (silos) and #79 (kind/exposure) as one PR or two?
6. **merge_map scoping** — honor a hit only if the target shares the silo (no migration), vs re-key `merge_map` by `(silo_id, from_name)` (cleaner, but a schema + backfill change)?
7. **Batch normalizers** — consolidate the two divergent `run_batch_normalization` implementations into one first, or silo-scope both in place (and test both)?
