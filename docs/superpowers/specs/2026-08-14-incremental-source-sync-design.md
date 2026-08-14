# Incremental Source Sync — Spec 1 (spine + vault adapter)

- **Date:** 2026-08-14
- **Status:** Draft (design approved in principle; pending spec review + implementation plan)
- **Scope:** Spec 1 of 2. This spec covers the shared **spine** (watched-source registry,
  scheduler, change detection, the upsert primitive, co-occurrence recompute) and the
  **vault** adapter end to end. The **repo** adapter is Spec 2 — fully outlined at the end of
  this document so it can be picked up seamlessly.

---

## 1. Problem

Today, ingestion is one-shot. A vault or a repo is ingested once; there is no mechanism to
keep the graph in sync as the underlying sources change over time. Two concrete gaps:

1. **No re-sync loop.** Nothing re-scans a vault or a repo on a cadence to pick up new,
   changed, or deleted documents.
2. **No update-in-place.** `_ingest_document` dedups purely by `content_hash`: identical
   content → skip; *changed* content → a brand-new document (with a de-duplicated title),
   leaving the old version stranded. There is no notion of "this is the same note, edited."

We want: *"every X hours, check the source; ingest new docs, update changed docs in place,
retract deleted docs — for both vaults and repos."*

## 2. Goals / Non-goals

**Goals (Spec 1)**
- A persistent registry of **watched sources** with a per-source cadence.
- A **worker scheduler sweep** that re-scans due sources (modeled on the existing judge sweep).
- **Change detection** keyed on a stable identity (`source_path`), not content hash.
- A single worker-side **`upsert_document` primitive** that handles create / update-in-place /
  soft-delete, used by both the vault adapter (Spec 1) and the refactored repo batch (Spec 2).
- **Co-occurrence as a deterministic recompute** from `entity_sources` (decision (b) below),
  scoped to the entities a changed document touches — so update and delete are clean.
- The **vault adapter** running end to end through the spine.

**Non-goals (Spec 1)**
- The repo adapter and its partial re-summarization thresholds — that is **Spec 2** (§13).
- Consolidating the orchestrator's inline `_ingest_document` and the worker's extraction into
  one shared package — larger refactor, documented as future work (§12).
- Any change to the `/graph` read path or the cached snapshot format. The frontend is untouched.

## 3. Key insight — "a batch is just a series of docs"

`extract_batch` (worker) and `_ingest_document`'s co-occurrence helper (orchestrator) compute
co-occurrence with the **identical** chunk-level algorithm. The only difference is the *write*:
the inline path writes one retractable row per pair **per document** (`source_chunk` set); the
batch path folds everything into **one aggregated row per pair** with `source_chunk = NULL` and
`weight += n`, which has no per-document provenance and cannot be cleanly retracted.

That divergence is an incidental row-count optimization (#73), not a semantic difference. Spec 1
converges both worker paths on **one representation** and **one write strategy** (decision (b)),
so a batch genuinely becomes a loop over a single per-document primitive.

### Process-boundary reality (why "one literal function" is scoped to the worker)

The orchestrator and the worker are **separate Python packages** with **separate extraction
stacks** (`worker/src/classifier.py`, `worker/src/normalizer.py`, inline extraction in
`extract_batch`; the worker does not import `orchestrator/src/pipeline`). `db.py` is duplicated
across both and kept byte-identical by the schema-mirror test — that is the existing pattern for
shared surface.

Therefore Spec 1 realizes the unification **inside the worker**: factor `upsert_document` out of
`extract_batch`, and have the vault/sync jobs call it. The orchestrator's interactive inline
upload route is left as-is for now (it already writes retractable per-chunk co-occurrence rows,
so it is not the problem child). Fully merging the two extraction stacks is future work (§12).

## 4. Architecture — three layers, and what changes

1. **Source facts** — `documents`, `chunks`, `entity_sources(entity_id, document_id, chunk_id)`.
   Source of truth. *Changed by sync.*
2. **Materialized edges** — `relationships` co-occurrence rows. **Stays materialized + cached.**
   *How they are refreshed changes* (recompute instead of accumulate). ← the only real change
3. **Cached graph snapshot** — the blob `/graph` serves. **Unchanged.** Sync marks it dirty via
   the existing `mark_graph_dirty`; the existing snapshot sweep rebuilds it.

Nothing moves to read-time or to the frontend. The frontloaded-and-cached architecture is
preserved; only the layer-2 *update mechanism* changes.

## 5. Schema changes

All new tables/columns read by one service and written by the other **must be mirrored
byte-identical** in `orchestrator/src/db.py` and `worker/src/db.py`, and added to the
`_MIRRORED_TABLES` / `_MIRRORED_INDEXES` sets in `test_schema_mirror.py`. Column adds go through
the existing idempotent `ALTER TABLE` migration block (same pattern as `role` /
`emits_cooccurrence`), never a bare `CREATE`.

**`documents`** — add:
- `modified_at TIMESTAMP` — stamped on every update-in-place (you named this explicitly).
- `invalid_at TIMESTAMP` — soft-delete marker (mirrors `entities.invalid_at` /
  `relationships.invalid_at`). Reads for active documents filter `WHERE invalid_at IS NULL`.
- `source_id TEXT` — FK to `watched_sources.id`, nullable (a doc may be unmanaged). Lets a sweep
  enumerate "the docs I currently own" to compute deletions.
- Index `idx_documents_source_path ON documents(source_path)` — identity lookups join on it.

**`watched_sources`** (new, mirrored):
```sql
CREATE TABLE IF NOT EXISTS watched_sources (
    id TEXT PRIMARY KEY,
    type TEXT,                    -- 'vault' | 'repo'
    uri TEXT,                     -- vault dir (as the worker sees it) | git url/path
    noosphere TEXT,               -- workspace this source feeds
    cadence_hours REAL DEFAULT 24,
    config_json TEXT,             -- adapter-specific (ext filter, branch, thresholds…)
    enabled INTEGER DEFAULT 1,
    last_scanned_at TIMESTAMP,
    last_status TEXT,             -- 'ok' | 'error' | 'running'
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 6. Identity & change detection

- **Identity = `source_path`** (per noosphere). Stable across edits. This is a deliberate switch
  from today's content-hash identity: **copies of the same content at different paths are now
  distinct documents** (matches your "if a user treats them as separate, they are separate").
  Content-hash dedup no longer suppresses a second path.
- **Change key = `content_hash`** (already stored + indexed) — "did the doc at this path change."
- **Pathless docs** (e.g. pasted-text uploads with `source_path IS NULL`) keep today's
  content-hash dedup behavior and are never change-tracked. Only path-bearing docs sync.

### Change-action decision table (per scanned source file)

| Condition (by `source_path` within the noosphere)        | Action                          |
|----------------------------------------------------------|---------------------------------|
| No document at this path                                  | **create** (full ingest)        |
| Document exists, `content_hash` differs                   | **update-in-place** (§7)        |
| Document exists, `content_hash` equal                     | **skip**                        |
| Document owned by this source, path absent from the scan  | **soft-delete** (§8)            |

## 7. The `upsert_document` primitive (worker)

Factored out of `extract_batch`. Single entry point for create + update:

```
upsert_document(store, *, source_path, title, content, source_id,
                emits_cooccurrence: bool) -> UpsertResult
```

Steps:
1. Compute `content_hash`. Look up the active document by `(noosphere, source_path)`.
2. **Unchanged** → return `skipped`.
3. **Update** → retract the old version's derived rows first, then re-ingest the new content:
   - Collect `affected_entities` = entities in the old doc's `entity_sources`.
   - Delete the old doc's `chunks`, `entity_sources`, and its **own** co-occurrence rows.
   - Re-chunk, re-classify, re-extract, re-normalize (same spec-driven path `extract_batch`
     already uses), producing new `entity_sources`. Add the new doc's entities to
     `affected_entities`.
   - Update the `documents` row in place (same `id`), set `modified_at = CURRENT_TIMESTAMP`.
   - **Recompute co-occurrence** for `affected_entities` (§9).
4. **Create** → the normal ingest path, then recompute co-occurrence for the new entities.
5. `mark_graph_dirty(noosphere)`. Commit per document (crash-safe / resumable, as the vault
   script already does).

`emits_cooccurrence` is passed through to §9 — `False` skips edge production entirely (repo
summary/module docs in Spec 2; always `True` for vault notes). It maps to the existing
`document_collections.emits_cooccurrence` gate.

`extract_batch` becomes a thin loop: `for doc in docs: upsert_document(...)`. Its current inline
extraction + co-occurrence block is deleted in favor of the primitive.

## 8. Deletion semantics (soft-delete)

A path a source used to have but no longer does → **soft-delete**, never hard-delete:
- Set `documents.invalid_at = CURRENT_TIMESTAMP`.
- Retract its derived contributions exactly as the update path does (delete its `chunks` /
  `entity_sources` / own co-occurrence rows; collect `affected_entities`; recompute §9).
- Entities left with zero remaining `entity_sources` after retraction are soft-deleted
  (`entities.invalid_at`) so no ghost nodes linger. This reuses the corrections `invalid_at`
  machinery; the action is reversible.

## 9. Co-occurrence recompute — decision (b), scoped

Co-occurrence is a **deterministic projection of `entity_sources`** (which carries
`entity_id, document_id, chunk_id`): two entities co-occur when they share a `chunk_id`. Rather
than mutate an aggregate incrementally, we **delete the affected aggregated rows and re-derive
them** from `entity_sources`, scoped to the entities the changed document touched.

Recompute for a set `A` of affected entities:
1. Delete aggregated co-occurrence rows (`type='co_occurs'`, the sync representation) where
   `from_entity IN A OR to_entity IN A` **and** the row is not human-invalidated
   (`invalid_at IS NULL` rows are rebuilt; invalidated rows are left untouched so a human
   decision is never revived).
2. Re-derive from `entity_sources` over active (non-invalid) entities:
   ```sql
   SELECT s1.entity_id AS a, s2.entity_id AS b, COUNT(DISTINCT s1.chunk_id) AS w
   FROM entity_sources s1
   JOIN entity_sources s2 ON s1.chunk_id = s2.chunk_id AND s1.entity_id < s2.entity_id
   WHERE (s1.entity_id IN (A) OR s2.entity_id IN (A))
   GROUP BY a, b;
   ```
   Insert one aggregated `co_occurs` row per pair with the summed weight.

**Cost:** bounded by the neighborhood of `A`, not the whole graph. Its cost on the real corpus
should be measured during implementation; if it is material on large collections, batch the
recompute once per sweep (union of all `A` across the sweep's changed docs) rather than per doc.

**Representation reconciliation (explicit design detail):** today there are two co-occurrence
representations — the worker's aggregated `source_chunk IS NULL` rows and the orchestrator upload
path's per-chunk `source_chunk` rows. A given document is produced by exactly one path, so they
do not double-count for the same doc. Spec 1's sync path owns the aggregated representation. The
recompute above must therefore scope to the aggregated rows only and leave per-chunk upload rows
alone (graph readers already `SUM` weights across rows). Verifying no reader double-counts across
the two representations is a test obligation (§11).

## 10. The spine

**Registry route (orchestrator).** `POST /watched-sources` (add), `GET /watched-sources` (list),
`PATCH /watched-sources/{id}` (enable/disable, cadence). Thin CRUD over `watched_sources`. This
is where "which repos, at what cadence" lives — just rows.

**Scheduler (worker).** Extend the existing sweep loop in `worker/src/main.py` (the
`now - last_sweep >= interval` pattern used for the judge sweeps). Add
`source_scan_interval_seconds` (config; env `SOURCE_SCAN_INTERVAL_SECONDS`, default 900). Each
tick: select `enabled` sources where `last_scanned_at + cadence_hours` is due, and enqueue a
`scan_source` job per source (so scans are ordinary jobs, retryable via the #74 machinery, and
visible in `/jobs`). Set `last_status='running'` on claim.

**`scan_source` job (worker).** The adapter dispatch:
1. Resolve the adapter by `type`.
2. Adapter enumerates current `(source_path, title, content)` tuples.
3. Apply the §6 decision table: create / update / skip via `upsert_document`; compute the
   deletion set from `documents WHERE source_id = ? AND invalid_at IS NULL` minus the scanned
   paths, and soft-delete those (§8).
4. Stamp `last_scanned_at`, `last_status`, `last_error`.

## 11. Vault adapter (Spec 1 deliverable)

Enumerate the vault: `rglob('*')` filtered by `config_json.ext` (default `.md`), skipping empty
files. For each: `source_path` = path as the worker sees it (staged under the data mount),
`title` = file stem, `content` = file text. `emits_cooccurrence = True` (flat leaves, no
hierarchy). Everything else is the shared spine.

This supersedes the fork's standalone `scripts/vault-run/ingest_vault.py`: the resumable
per-note commit behavior is preserved (it falls out of `upsert_document` committing per doc), but
it now runs as a scheduled worker job with real change/delete handling instead of a one-shot
content-hash-dedup script.

## 12. Testing

- **Orchestrator (native pytest):** registry route CRUD; migration adds the new columns
  idempotently; schema-mirror test includes `watched_sources` + the new `documents` columns/index.
- **Worker (docker `uv run`, per CLAUDE.md):** `upsert_document` create/update/delete paths;
  co-occurrence recompute correctness (update a doc, assert affected edges match a full
  from-scratch recompute; assert unaffected edges are byte-identical); soft-delete retracts edges
  and orphans; deletion-set computation; **no-double-count across the two co-occurrence
  representations**; the vault adapter's create/change/delete on a temp vault fixture.
- **Regression guard:** refactoring `extract_batch` onto the primitive must leave a fresh repo
  ingest's graph identical to today's (golden co-occurrence counts on a fixture repo).

## 13. Migration / back-compat

- New columns default NULL / sensible values; existing rows unaffected. Existing documents have
  `source_id IS NULL` → treated as unmanaged, never touched by a sweep until adopted by a source.
- The change to path-based identity affects **only** the sync path. The interactive upload route
  keeps content-hash dedup, so existing behavior is unchanged for manual uploads.

## 14. Risks / open questions

- **Recompute cost** on large collections — measure; fall back to per-sweep batched recompute.
- **Vault/worker path visibility** — the vault must be reachable at `watched_sources.uri` *inside
  the worker container* (data-mount staging). Ties into task #24 (bind-mount vs volume).
- **Two extraction stacks** (orchestrator vs worker) may classify/extract differently; sync uses
  the worker's. Acceptable for Spec 1; consolidation is future work.
- **Concurrent sweep vs manual ingest** on the same noosphere — rely on WAL + per-doc commits;
  the scheduler enqueues jobs rather than doing work in the loop, so the existing job machinery
  serializes appropriately.

---

## 15. Spec 2 — Repo adapter (documented now for continuity)

Spec 2 reuses the **entire spine** unchanged (registry, scheduler, `scan_source`,
`upsert_document`, co-occurrence recompute). It adds only the repo adapter and its partial
re-ingestion logic. Written up here so it can be started without re-deriving context.

**Enumeration & identity.** A repo source enumerates the git tree at `HEAD` for its branch.
Identity is `(collection, repo-relative file path)` mapped onto `source_path`. Change detection
can shortcut via git: `git diff --name-status <last_synced_sha>..HEAD` yields the exact
added/modified/deleted set, so the adapter need not re-hash every file (store `commit_sha` per
scan on the collection; fall back to content-hash if no prior sha).

**Hierarchy — the real nuance.** Repos produce three doc roles (`document_collections.role`):
`leaf` (per-file intent), `group` (module), `root` (repo rollup). Only `leaf` docs
`emits_cooccurrence = True`. Partial re-ingestion:
- **Changed leaf files** → re-featurize just those files via codesum → `upsert_document` each.
- **Module (`group`) summaries** → regenerate only for modules containing a changed leaf, and
  only past a **change threshold** (e.g. ≥ N leaves in the module changed, or any add/delete of a
  leaf), to avoid re-summarizing a whole module for a one-line change. `emits_cooccurrence=False`.
- **Repo (`root`) rollup** → regenerate once per sync if any module changed, or past a
  repo-level threshold (fraction of modules touched). `emits_cooccurrence=False`.
- **Deleted files** → soft-delete the leaf doc (spine §8), then re-evaluate its module/root
  summaries under the same thresholds.

**Thresholds live in `config_json`** per source (`leaf_change_ratio`, `module_change_ratio`),
so re-summarization aggressiveness is tunable without code changes.

**"Series of repos"** is just multiple `watched_sources` rows of type `repo`; the scheduler fans
out `scan_source` jobs across them. No special multi-repo machinery.

**Featurizer reuse.** The adapter calls `orrery-codesum` for the changed subset only, mirroring
`ingest_repo.py` stage-for-stage but scoped to the diff rather than the whole tree. Tracker-run
ingestion (`ingest_tracker_runs.py`, tracksum) gets the same treatment as a follow-on, since a
tracker run *is* a repo downstream.

**Spec 2 testing.** git-diff-driven change set; threshold-gated re-summarization (assert a
sub-threshold change does *not* redo the module summary); leaf delete cascades to summary
re-evaluation; co-occurrence recompute stays correct when only a subset of leaves change.

**Open question for Spec 2.** Whether to key repo change detection on git sha (fast, requires a
git checkout in the worker) or fall back to per-file content hashing (path-based, works on staged
bundles without git). Likely support both, chosen by whether `uri` resolves to a git repo.
