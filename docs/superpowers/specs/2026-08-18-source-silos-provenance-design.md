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

Silo lives on **documents**, but normalization operates on **entities**. An entity's effective silo is the silo(s) of its source documents (`entity_sources → documents.silo_id`). Because auto-merge is silo-scoped, an entity's sources stay within one silo until a human cross-silo merge — so "the entity's silo" is well-defined in the common case.

Three call sites must become silo-aware (all identified, grounded):

- **`orchestrator/src/pipeline/normalizer.py::normalize_entity`** (per-entity, inline during ingest). The `merge_map` / existing-entity lookup for a new mention from a doc in silo *S* must only match entities whose sources are in *S*. Concretely: the candidate `SELECT` joins `entity_sources → documents` and filters `documents.silo_id = S` (or `silo_id IS NULL` when *S* is null).
- **`orchestrator/src/pipeline/embedding_normalizer.py::run_batch_normalization`** and **`worker/src/normalizer.py::run_batch_normalization`** (batch, faiss candidate search — currently partitioned *per type*, `worker/src/normalizer.py:161`). Candidate search becomes partitioned **per (type, silo)**: an entity only clusters against candidates sharing its silo. Both implementations must change identically (they are a schema/behaviour mirror — see the schema-mirror discipline).
- **Cross-silo detection → proposal.** When the batch normalizer finds a high-similarity pair that straddles silos (or silo ↔ null), instead of merging it files a `graph_issues` proposal (`graph_repair.py`) — `action=merge`, the two entity ids, similarity as rationale — for human review. This reuses the exact merge/rollback bookkeeping in `docs/graph-corrections.md`, so a human-approved cross-silo merge (and its undo) stays consistent.

**Open scoping decision (for review):** is the within-silo scope *hard* ("never auto-merge across silo, full stop") or is there a per-noosphere policy knob? Default proposal: **hard by default**, cross-silo only via corrections. No config knob in v1 (YAGNI); revisit if a real need appears.

## 4. Provenance `kind` (the #79 remnant)

Each silo has a **`kind`** — a small, closed vocabulary. Candidate set (final list is a review decision):

| `kind` | Meaning | Default `emits_cooccurrence` | Agent trust signal |
|---|---|---|---|
| `neutral_summary` | Map of territory, attestable vs `source_path` (codesum/tracksum) | leaf: yes / rollup: no (existing gate) | high — "what the code does" |
| `human_vault` | Primary human notes (Obsidian, uploads under a vault) | yes | medium — human-authored |
| `agent_report` | Derived agent claims — retros, best-practice sweeps | **gated/down-weighted** | low — "what an agent thinks" |
| `human_reviewed` | An `agent_report` a human vetted | yes | high |

The `kind` drives two things and is **read-exposed** (see §6):
- **Co-occurrence emission** — reuses the existing `document_collections.emits_cooccurrence` lever; `agent_report` silos default to gated so opinion docs don't reshape shared edge weights.
- **Agent trust** — surfaced in reads so a consuming agent can weight or disbelieve a node's provenance.

`kind` is **not** used for normalization scoping — scoping is by silo *id* (§3). Two `neutral_summary` repos are still different silos and don't auto-merge. `kind` is metadata about the silo, for emission + trust, not a scoping key.

## 5. Data model

- **`documents.silo_id`** — the silo key. Proposal: **reuse/rename around the existing `source_id`** rather than add a parallel column. Reconciliation needed (a real design item): today a watched-source doc carries `source_id`, a repo/tracker doc carries `collection_id` (via `document_collections`), and a one-off carries neither. Define `silo_id` as the document's **single source-of-origin UUID**, populated at ingest from whichever applies; null for one-offs. (Decision for review: one unified `silo_id` column vs a computed view over `source_id`/`collection_id`.)
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

- **Scoping unit tests:** two silos with an identically-named entity → `normalize_entity` and both `run_batch_normalization`s keep them distinct; same name *within* one silo → merges. Null-silo docs still normalize among themselves (regression: today's behaviour unchanged).
- **Cross-silo proposal:** a high-similarity cross-silo pair produces a `graph_issues` row (not a merge); approving it merges and `rollback_merge` reverses it.
- **Emission:** an `agent_report` silo's docs do **not** emit co-occurrence edges (or are down-weighted) by default.
- **Read exposure:** `get_entity` / graph snapshot include silo + kind.
- **Schema mirror:** the two `run_batch_normalization` implementations and any mirrored DDL stay identical (`test_schema_mirror`).

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
