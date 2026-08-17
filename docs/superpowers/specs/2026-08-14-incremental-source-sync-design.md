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
- Consolidating the orchestrator's and worker's full **extraction** stacks (classifier,
  normalizer, extractor) into one shared package — larger refactor, future work (§12). Note:
  Spec 1 *does* unify the narrow **co-occurrence write** across both services (§9), because
  leaving two co-occurrence representations double-counts once a recompute runs globally.
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
upload route keeps its own extraction stack — but its **co-occurrence write is converted** to the
same recompute-from-`entity_sources` helper (§9), because two coexisting co-occurrence
representations double-count once a recompute runs globally. That recompute helper is the one new
piece of cross-service surface; it is mirrored in both services like the schema itself. Fully
merging the two *extraction* stacks remains future work (§12).

## 4. Architecture — three layers, and what changes

1. **Source facts** — `documents`, `chunks`, `entity_sources(entity_id, document_id, chunk_id)`.
   Source of truth. *Changed by sync.*
2. **Materialized edges** — `relationships` co-occurrence rows. **Stays materialized + cached.**
   *How they are refreshed changes* (recompute instead of accumulate). ← the only real change
3. **Cached graph snapshot** — the blob `/graph` serves. **Unchanged.** Sync marks it dirty via
   the existing `mark_graph_dirty`; the existing snapshot sweep rebuilds it.

Nothing moves to read-time or to the frontend. The frontloaded-and-cached architecture is
preserved; only the layer-2 *update mechanism* changes.

### Invariant core vs. pluggable featurizer

Orthogonal to the three layers is the pipeline's one seam:

```
SOURCE ─[ featurize ]→ DOCUMENTS ──→ [ INVARIANT CORE ] ──→ graph
                       (title, content,    persist · chunk · classify ·
                        source_path,        extract entities · normalize ·
                        role, emits_coocc)  co-occur (projection) · snapshot
```

Everything right of **DOCUMENTS** is invariant — `upsert_document` + the §9 projection + change
detection + snapshot, identical for every source. The only per-source-type code is the
**featurizer**: `source → iterator[document]`. Orrery already runs two shapes of it — repos
explode into a *hierarchy* of summary docs (codesum: leaf/group/root, only leaves emit
co-occurrence); notes/uploads map to a single doc. A featurizer that yields 200 docs just calls
`upsert_document` 200 times; the core is document-granular and cardinality-agnostic.

Deliberately **not** built: any plugin framework. A featurizer is a plain function with three call
sites (upload, vault, repo); no registry/abstraction until there is a fourth (YAGNI).

### Two levels of change detection

Separating these is what avoids wasted model cost:
1. **Source-level (inside the featurizer):** which raw inputs changed → what to re-featurize.
   Repo: `git diff` re-summarizes only changed leaves (short-circuit *before* the LLM call).
   Vault: note mtime/hash. This is the Spec 2 partial-reingest logic.
2. **Document-level (in the core):** given a produced doc, did its content change → create /
   update / skip (§6). The cheap safety net that catches "re-featurized but output identical."

For a vault the two nearly coincide; for a repo they diverge — exactly why Spec 2 layers its own
source-level diffing on top of the shared core.

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

> **`documents` becomes a newly-mirrored table.** It is *not* currently in `_MIRRORED_TABLES`;
> once the worker writes `invalid_at`/`modified_at`/`source_id` and the orchestrator reads them,
> it is cross-service surface — add `documents` (and `idx_documents_source_path`) to the mirror
> sets, and keep the DDL byte-identical in both `db.py` files.

> **`invalid_at` read-site sweep (implementation task).** Adding the column is not enough — every
> read that lists or joins `documents` must add `WHERE invalid_at IS NULL` or it will surface a
> ghost row. Enumerate and patch: the documents list/detail routes, the reader-spans route, the
> graph-build document/`entity_sources` joins, and **search** (which per CLAUDE.md does not yet
> thread `invalid_at` even for entities). This is an explicit checklist item, not incidental.

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
1. Compute `content_hash`. Look up the active document by `source_path` **within this workspace
   DB**. **Adoption rule:** match a doc with `source_id = <this source>` (already managed) OR
   `source_id IS NULL` (an unmanaged manual upload at the same path) — in the latter case set its
   `source_id` to adopt it rather than create a duplicate. Never match a doc owned by a *different*
   source; two sources claiming one path is a config error surfaced in `watched_sources.last_error`.
2. **Unchanged** → return `skipped`.
3. **Update** → retract the old version's derived rows first, then re-ingest the new content:
   - Collect `affected_entities` = entities in the old doc's `entity_sources`.
   - Delete the old doc's `chunks` and `entity_sources`. Co-occurrence rows are **not** deleted
     per-doc here — under the §9 invariant they are owned solely by the recompute, which retracts
     the old contribution when it re-derives from the now-updated `entity_sources`.
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

A path a source used to have but no longer does → the **document** is soft-deleted and its
derived rows retracted:
- Set `documents.invalid_at = CURRENT_TIMESTAMP` (the doc row survives, so a re-appearing file
  re-attaches to the same identity and audit history is kept).
- Delete its `chunks` and `entity_sources`; collect `affected_entities`; recompute co-occurrence
  (§9), which drops the deleted doc's edge contribution.
- Entities left with zero remaining `entity_sources` are soft-deleted (`entities.invalid_at`) so
  no ghost nodes linger.
- **Reversibility scope (corrected):** this is *not* a corrections-style fully-reversible undo —
  the deleted doc's `chunks`/`entity_sources` are hard-removed, so a re-appearing file re-ingests
  fresh at the same `source_path` rather than being restored. That soft-deleting a doc and pruning
  its `entity_sources` does not corrupt an existing human merge/undo recorded in
  `normalization_log` is a test obligation (§12).

## 9. Co-occurrence recompute — decision (b), one invariant across all paths

**Invariant:** every valid `relationships` row of `type='co_occurs'` is a **pure projection of
`entity_sources`** — *no ingestion or document-mutation path writes co-occurrence rows directly;
the recompute helper is their sole writer.* Three existing writers must be converted to call it
(this is the complete list — a missed one leaves stale, weight-inflated edges):
- the orchestrator **upload** path's `upsert_cooccurrence` (`sqlite_store.py`) → recompute over
  the uploaded doc's entities;
- `extract_batch`'s aggregated `weight += n` write → via `upsert_document` (§7);
- the interactive **document-delete** retraction in `SQLiteDocumentRepository.delete()`
  (`sqlite_store.py:160-164`), which today deletes edges by `source_chunk IN (chunks of doc)`.
  Once projected rows carry `source_chunk = NULL` that predicate becomes a **no-op**, leaving
  inflated edges for every surviving entity the doc touched — so `delete()` must instead drop the
  doc's `entity_sources`, collect `affected_entities`, and call the recompute (the §8 shape).

The **corrections** path (`apply_merge` / `rollback_merge`, `graph_repair.py`) also writes
`co_occurs` rows; those are *sanctioned* corrections-path writers producing pair/weight-equivalent
rows and stay — but they should emit `source_chunk = NULL` too, so every row is uniformly
projected. The double-count arises whenever two writers use different representations under a
global recompute — the blocking flaw this design must not ship with.

Two entities co-occur when they share a `chunk_id` (`entity_sources` carries
`entity_id, document_id, chunk_id`). Recompute for a set `A` of affected entities:

1. **Delete** the projected rows to rebuild:
   ```sql
   DELETE FROM relationships
   WHERE type = 'co_occurs' AND invalid_at IS NULL
     AND (from_entity IN (A) OR to_entity IN (A));
   ```
   `invalid_at IS NULL` preserves human-invalidated edges (a corrections decision is never
   revived). No `source_chunk` scoping is needed: under the invariant there is **no** second
   representation to protect — all valid `co_occurs` rows are projected and safe to rebuild.
2. **Re-derive** from `entity_sources`, restricted to **active (non-invalid) entities**, and
   insert one row per pair:
   ```sql
   SELECT s1.entity_id AS a, s2.entity_id AS b, COUNT(DISTINCT s1.chunk_id) AS w
   FROM entity_sources s1
   JOIN entity_sources s2
     ON s1.chunk_id = s2.chunk_id AND s1.entity_id < s2.entity_id
   JOIN entities e1 ON e1.id = s1.entity_id AND e1.invalid_at IS NULL
   JOIN entities e2 ON e2.id = s2.entity_id AND e2.invalid_at IS NULL
   WHERE (s1.entity_id IN (A) OR s2.entity_id IN (A))
   GROUP BY a, b;
   ```
   The `entities … invalid_at IS NULL` joins are required (a soft-deleted entity keeps its
   `entity_sources` rows, so without them it would still project edges); this matches the
   established recompute in `apply_merge` (`graph_repair.py:292-295`). Skip any pair that already
   has a surviving *invalidated* `co_occurs` row — the skip lookup must **normalize endpoint
   order** (check both `(a,b)` and `(b,a)`), since an invalidated row from `apply_merge` may be
   stored unordered. Documents with `emits_cooccurrence = False` contribute no `entity_sources` in
   the sync path, so they never enter the projection.

**Where the helper lives.** The recompute is pure SQL against a connection, called by both the
worker (`upsert_document`) and the orchestrator (upload route). Like `db.py`, it is mirrored in
both services and covered by a mirror test — the one new piece of shared surface Spec 1 adds
(narrower than merging the extraction stacks, which stays out of scope).

**Cost:** bounded by the neighborhood of `A`, not the whole graph. Measure on the real corpus; if
material on large collections, batch the recompute once per sweep over the union of all `A`.

**One-time migration.** Existing rows written by the old two-representation code (aggregated
`source_chunk IS NULL` from `extract_batch`; per-pair `source_chunk` from uploads) are reconciled
to the projection by a **full recompute per workspace** on first run after deploy (bounded, pure
SQL, no LLM). Human-invalidated rows are preserved. Call this out in §13.

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

**Per-DB routing (workspaces are separate SQLite files).** `watched_sources` lives **in each
workspace DB**, so `(source_id, source_path)` identity is unambiguous within a file and no
cross-DB coordination is needed. The registry route writes to the target workspace's DB (the
route is already workspace-scoped). The worker sweep **already iterates `db_paths`** — for each
workspace DB it reads that DB's own `watched_sources` and enqueues `scan_source` jobs into the
same DB, so jobs land where their data is. The `watched_sources.noosphere` column is therefore a
label/sanity field, not a routing key (identity is per-file); keep it for provenance/logging.

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

**Document model — unchanged from today (decided).** A note maps to **one document**, split into
the current **fixed-size** chunks. Chunks stay purely the **extraction + search** unit (small
models extract entities per chunk; chunks carry embeddings), and **domains are classified at the
document level** (`document_domains`) — a note is treated as one concept in one place. Two things
are explicitly **deferred**, both clean later changes behind the same seam with no schema or
identity impact:
- *Sections-as-documents* (per-section domains + identity) — costs N× classification per note for
  a granularity prose rarely needs; codesum already proves the pattern for code when it's wanted.
- *Smarter / user-configurable chunking* (heading-aware, per-source overrides) — the fixed-size
  chunker is retained for Spec 1; a `segment strategy` swap can come later, optionally
  user-specified.

This supersedes the fork's standalone `scripts/vault-run/ingest_vault.py`: the resumable
per-note commit behavior is preserved (it falls out of `upsert_document` committing per doc), but
it now runs as a scheduled worker job with real change/delete handling instead of a one-shot
content-hash-dedup script.

## 12. Testing

- **Orchestrator (native pytest):** registry route CRUD; migration adds the new columns
  idempotently; schema-mirror test includes `documents` (newly mirrored) + `watched_sources` +
  `idx_documents_source_path`; the upload route's co-occurrence now equals the projection (assert
  an interactive upload's edges match a from-scratch projection of `entity_sources`); the recompute
  helper's mirror test (byte-identical in both services); the `invalid_at` read-site sweep
  (§5) — a soft-deleted doc must not appear in the documents list, reader, graph build, or search;
  **interactive `DELETE /documents/{id}` leaves the graph equal to a from-scratch projection**
  (guards the `source_chunk` no-op regression — critical because the worker suite, which the rest
  of this flow relies on, is not in CI, so this orchestrator test is the automated backstop).
- **Worker (docker `uv run`, per CLAUDE.md):** `upsert_document` create/update/delete paths;
  **projection invariant** — after any create/update/delete, every valid `co_occurs` row is
  reproducible by a full from-scratch projection of `entity_sources`, and no valid row coexists
  with a human-invalidated one (this replaces the old "no double-count across two representations"
  test, since there is now one representation); update leaves unaffected edges byte-identical;
  soft-delete retracts edges + orphans and does **not** corrupt a `normalization_log` merge/undo;
  deletion-set computation; the adoption rule (a vault scan adopts an unmanaged upload at the same
  path rather than duplicating); the vault adapter's create/change/delete on a temp vault fixture.
- **Regression guard:** refactoring `extract_batch` + the upload path onto the projection must
  leave a fresh repo ingest's *and* a fresh single-upload's graph co-occurrence identical to a
  from-scratch projection (golden counts on fixtures).

## 13. Migration / back-compat

- New columns default NULL / sensible values; existing rows unaffected. Existing documents have
  `source_id IS NULL` → treated as unmanaged, never touched by a sweep until adopted by a source.
- The change to path-based identity affects **only** the sync path. The interactive upload route
  keeps content-hash dedup for *identity*, but its co-occurrence **write** changes to the shared
  projection helper (§9) — behavior-preserving for edge weights, verified by the golden test.
- **One-time co-occurrence reconciliation** (§9): on first run after deploy, a full recompute per
  workspace rewrites all `co_occurs` rows as the projection of `entity_sources`, collapsing the
  old aggregated + per-pair rows into one representation. Bounded, pure SQL, preserves
  `invalid_at` rows. Idempotent — safe to re-run.

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
