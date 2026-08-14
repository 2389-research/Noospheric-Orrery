# Incremental Source Sync — Spec 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add scheduled, incremental re-ingestion of an Obsidian vault (new/changed/deleted notes update the graph in place), on a unified per-document pipeline shared with existing ingestion.

**Architecture:** A single worker-side `upsert_document` primitive handles create / update-in-place / soft-delete keyed on `source_path`. Co-occurrence becomes a **pure projection of `entity_sources`** with one shared writer (the `recompute_cooccurrence` helper), so update/delete are clean. A `watched_sources` registry + a worker sweep (modeled on the judge sweep) re-scans due sources and enqueues `scan_source` jobs; a vault featurizer maps notes → documents.

**Tech Stack:** Python, FastAPI (orchestrator), a polling worker, SQLite (WAL), pytest. Two separate packages (`orchestrator/`, `worker/`) with a byte-mirrored `db.py`.

**Spec:** `docs/superpowers/specs/2026-08-14-incremental-source-sync-design.md` (read it first — this plan implements Spec 1; §-references below point into it).

---

## Conventions & gotchas (read before starting)

- **Orchestrator tests run natively:** `cd orchestrator && pytest tests/ -v`. A clean run is "3 failed" (pre-existing, deselected in CI — see CLAUDE.md). Anything beyond those three is yours.
- **Worker tests run in the container**, never natively (native segfaults on torch/faiss). Per CLAUDE.md:
  ```bash
  docker-compose build worker
  docker-compose up -d --no-deps worker         # check /stats active_jobs==0 first
  docker exec noospheric-github-worker-1 rm -rf /app/worker/tests
  docker cp worker/tests noospheric-github-worker-1:/app/worker/tests
  docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
    noospheric-github-worker-1 uv run --with pytest --with pytest-asyncio python -m pytest tests/ -q
  ```
- **Schema-mirror invariant:** any table/index/shared helper written by one service and read by the other must be **byte-identical** in `orchestrator/src/db.py` and `worker/src/db.py`, and listed in `orchestrator/tests/test_schema_mirror.py`. Edit both copies in the same step, always.
- **WAL:** never open SQLite directly — use `get_connection()` (sets `busy_timeout` then `journal_mode=WAL`).
- **Commit after every green step.** Work on the branch `feat/incremental-source-sync-spec` (the spec already lives there).

---

## File structure

**Phase 1 — co-occurrence projection (shared core, highest risk)**
- Modify: `orchestrator/src/db.py` + `worker/src/db.py` — add `recompute_cooccurrence(conn, ids)` (byte-identical).
- Modify: `orchestrator/tests/test_schema_mirror.py` — assert the helper is mirrored.
- Modify: `orchestrator/src/routes/ingest.py:134-138,174-180` — upload path calls the helper.
- Modify: `worker/src/jobs/extract_batch.py:150-180` — batch path calls the helper.
- Modify: `orchestrator/src/repositories/sqlite_store.py:158-164` — `delete()` retracts via the helper.
- Modify: `orchestrator/src/pipeline/graph_repair.py:299-300,340` — merge/rollback emit `source_chunk=NULL` (nice-to-have).
- Create: `scripts/reconcile_cooccurrence.py` — optional one-time global backfill.

**Phase 2 — the spine**
- Modify: `orchestrator/src/db.py` + `worker/src/db.py` — `documents` columns (`modified_at`,`invalid_at`,`source_id`), `idx_documents_source_path`, `watched_sources` table (all mirrored).
- Modify: `orchestrator/tests/test_schema_mirror.py` — add `documents` + `watched_sources` + index.
- Modify: read sites for `invalid_at IS NULL` (enumerated in Task 8).
- Create: `worker/src/jobs/upsert_document.py` — the shared per-document primitive.
- Modify: `worker/src/jobs/extract_batch.py` — loop over the primitive.
- Create: `orchestrator/src/routes/watched_sources.py` — registry CRUD; register in `orchestrator/src/main.py`.
- Create: `worker/src/jobs/scan_source.py` — scan → diff → act.
- Modify: `worker/src/main.py:78-107` (dispatch), `:233-241` (sweep), `worker/src/config.py` + `orchestrator/src/config.py` (interval field).

**Phase 3 — vault featurizer**
- Create: `worker/src/featurizers/vault.py` — enumerate notes → `(source_path,title,content)`.
- Modify: `worker/src/jobs/scan_source.py` — dispatch to the vault featurizer.
- Create tests under `worker/tests/` and `orchestrator/tests/` per task.

---

# PHASE 1 — Co-occurrence as a single projection

Goal of the phase: every `co_occurs` row becomes a pure projection of `entity_sources`, written only by `recompute_cooccurrence`. This removes the two-representation double-count and makes retraction trivial. **No new features ship in this phase — the graph after a fresh ingest must be identical to a from-scratch projection.**

> **Correctness note (why no global migration is required):** `recompute_cooccurrence` deletes *all* valid `co_occurs` rows touching the affected entities (not scoped by `source_chunk`) before rebuilding. So the first time any entity is touched, its legacy rows (aggregated or per-pair) are cleaned and rebuilt correctly — reconciliation is lazy and per-neighborhood. The Task 5 script is an *optional* immediate global pass, not a correctness gate.

### Task 1: The `recompute_cooccurrence` helper (mirrored)

**Files:**
- Modify: `orchestrator/src/db.py` (add helper + `import uuid` if absent)
- Modify: `worker/src/db.py` (identical)
- Test: `orchestrator/tests/test_cooccurrence_projection.py` (create)
- Test: `orchestrator/tests/test_schema_mirror.py` (extend)

- [ ] **Step 1: Write the failing test**

Create `orchestrator/tests/test_cooccurrence_projection.py`:

```python
import uuid
from src.db import init_db, get_connection, recompute_cooccurrence


def _mk(conn, ent, doc, chunk):
    conn.execute("INSERT OR IGNORE INTO entities (id, canonical_name, type) VALUES (?,?,?)",
                 (ent, ent, "concept"))
    conn.execute("INSERT OR IGNORE INTO documents (id, title, content, content_hash) VALUES (?,?,?,?)",
                 (doc, doc, "x", doc))
    conn.execute("INSERT OR IGNORE INTO chunks (id, document_id, chunk_index, offset, length, text) "
                 "VALUES (?,?,0,0,1,'x')", (chunk, doc))
    conn.execute("INSERT INTO entity_sources (entity_id, document_id, chunk_id) VALUES (?,?,?)",
                 (ent, doc, chunk))


def test_projection_weight_counts_shared_chunks(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    # a & b co-occur in 2 chunks, a & c in 1
    for ch in ("k1", "k2"):
        _mk(conn, "a", "d1", ch); _mk(conn, "b", "d1", ch)
    _mk(conn, "a", "d1", "k3"); _mk(conn, "c", "d1", "k3")
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b", "c"]); conn.commit()
    rows = {(r["from_entity"], r["to_entity"]): r["weight"] for r in conn.execute(
        "SELECT from_entity, to_entity, weight FROM relationships WHERE type='co_occurs'")}
    assert rows[("a", "b")] == 2
    assert rows[("a", "c")] == 1
    assert all(r["source_chunk"] is None for r in conn.execute(
        "SELECT source_chunk FROM relationships WHERE type='co_occurs'"))


def test_recompute_is_idempotent_and_scoped(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    for ch in ("k1", "k2"):
        _mk(conn, "a", "d1", ch); _mk(conn, "b", "d1", ch)
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()   # twice
    n = conn.execute("SELECT COUNT(*) c FROM relationships WHERE type='co_occurs'").fetchone()["c"]
    assert n == 1   # no duplicate from re-running


def test_invalidated_edge_is_preserved_not_revived(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    for ch in ("k1", "k2"):
        _mk(conn, "a", "d1", ch); _mk(conn, "b", "d1", ch)
    conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight, invalid_at) "
                 "VALUES (?, 'a', 'b', 'co_occurs', 99, CURRENT_TIMESTAMP)", (str(uuid.uuid4()),))
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    rows = conn.execute("SELECT weight, invalid_at FROM relationships WHERE type='co_occurs'").fetchall()
    assert len(rows) == 1 and rows[0]["invalid_at"] is not None   # invalidated kept, no valid dup


def test_soft_deleted_entity_produces_no_edges(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    _mk(conn, "a", "d1", "k1"); _mk(conn, "b", "d1", "k1")
    conn.execute("UPDATE entities SET invalid_at = CURRENT_TIMESTAMP WHERE id = 'b'")
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM relationships WHERE type='co_occurs'").fetchone()["c"] == 0


def test_non_emitting_summary_doc_produces_no_edges(tmp_path):
    """A summary/rollup doc (document_collections.emits_cooccurrence=0) writes
    entity_sources but must NOT project edges — the hub-node guard. Entities OVERLAP
    with a leaf doc, so a disjoint-entity fixture would miss this (see review)."""
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO collections (id, name, path, root_path) VALUES ('c1','r','r','/r')")
    # leaf doc L (emits=1): a & b share chunk kL
    _mk(conn, "a", "L", "kL"); _mk(conn, "b", "L", "kL")
    conn.execute("INSERT INTO document_collections (document_id, collection_id, role, emits_cooccurrence) "
                 "VALUES ('L','c1','leaf',1)")
    # summary doc G (emits=0): a, b, c all in chunk kG — would spuriously link a-c,b-c,a-b
    _mk(conn, "a", "G", "kG"); _mk(conn, "b", "G", "kG"); _mk(conn, "c", "G", "kG")
    conn.execute("INSERT INTO document_collections (document_id, collection_id, role, emits_cooccurrence) "
                 "VALUES ('G','c1','root',0)")
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b", "c"]); conn.commit()
    rows = {(r["from_entity"], r["to_entity"]): r["weight"] for r in conn.execute(
        "SELECT from_entity, to_entity, weight FROM relationships WHERE type='co_occurs'")}
    assert rows == {("a", "b"): 1}   # only the leaf's edge, weight 1 (not 2, no a-c/b-c)
```

- [ ] **Step 2: Run it, expect failure**

Run: `cd orchestrator && pytest tests/test_cooccurrence_projection.py -v`
Expected: FAIL — `ImportError: cannot import name 'recompute_cooccurrence'`.

- [ ] **Step 3: Implement the helper in BOTH db.py copies (identical text)**

Add to `orchestrator/src/db.py` and `worker/src/db.py` (ensure `import uuid` at top of each):

```python
def recompute_cooccurrence(conn, affected_entity_ids):
    """Rebuild the co_occurs edges touching any of `affected_entity_ids` as a PURE
    PROJECTION of entity_sources (spec 2026-08-14 §9). This is the SOLE writer of
    co_occurs rows. Two entities co-occur when they share a chunk; weight = number of
    shared chunks. Human-invalidated edges (invalid_at NOT NULL) are preserved and
    never revived. Caller commits.
    """
    if not affected_entity_ids:
        return
    ids = list(dict.fromkeys(affected_entity_ids))
    ph = ",".join("?" * len(ids))
    # 1. Drop the VALID projected rows we're about to rebuild (keep invalidated ones).
    conn.execute(
        f"DELETE FROM relationships WHERE type='co_occurs' AND invalid_at IS NULL "
        f"AND (from_entity IN ({ph}) OR to_entity IN ({ph}))",
        ids + ids,
    )
    # 2. Re-derive from entity_sources over ACTIVE entities only, HONORING the
    #    emits_cooccurrence gate. A chunk belongs to exactly one document, so the two
    #    entity_sources rows of a pair share that document — gate once, on s1's document.
    #    Summary/rollup docs (document_collections.emits_cooccurrence=0) write
    #    entity_sources but must NOT emit edges; a doc with no collection row defaults to
    #    emit (COALESCE→1). This mirrors extract_batch's write gate and get_collection_routes.
    rows = conn.execute(
        f"""
        SELECT s1.entity_id AS a, s2.entity_id AS b, COUNT(DISTINCT s1.chunk_id) AS w
        FROM entity_sources s1
        JOIN entity_sources s2
          ON s1.chunk_id = s2.chunk_id AND s1.entity_id < s2.entity_id
        JOIN entities e1 ON e1.id = s1.entity_id AND e1.invalid_at IS NULL
        JOIN entities e2 ON e2.id = s2.entity_id AND e2.invalid_at IS NULL
        WHERE s1.chunk_id IS NOT NULL
          AND COALESCE((SELECT MIN(emits_cooccurrence) FROM document_collections
                        WHERE document_id = s1.document_id), 1) = 1
          AND (s1.entity_id IN ({ph}) OR s2.entity_id IN ({ph}))
        GROUP BY a, b
        """,
        ids + ids,
    ).fetchall()
    for r in rows:
        a, b, w = r["a"], r["b"], r["w"]
        # Skip if a human-invalidated edge exists for this pair (either endpoint order).
        if conn.execute(
            "SELECT 1 FROM relationships WHERE type='co_occurs' AND invalid_at IS NOT NULL "
            "AND ((from_entity=? AND to_entity=?) OR (from_entity=? AND to_entity=?)) LIMIT 1",
            (a, b, b, a),
        ).fetchone():
            continue
        conn.execute(
            "INSERT INTO relationships (id, from_entity, to_entity, type, weight, source_chunk) "
            "VALUES (?, ?, ?, 'co_occurs', ?, NULL)",
            (str(uuid.uuid4()), a, b, w),
        )
```

- [ ] **Step 4: Run the tests, expect pass**

Run: `cd orchestrator && pytest tests/test_cooccurrence_projection.py -v` → all PASS.

- [ ] **Step 5: Assert the helper is byte-mirrored**

In `orchestrator/tests/test_schema_mirror.py` add (adapt to the file's existing read helpers):

```python
import pathlib, re

def test_recompute_cooccurrence_is_mirrored():
    """The helper is byte-identical across the two db.py copies (same guarantee as the
    mirrored tables)."""
    def _fn(path):
        t = pathlib.Path(path).read_text()
        m = re.search(r"\ndef recompute_cooccurrence\(.*?(?=\n\S)", t, re.S)
        assert m, f"recompute_cooccurrence not found in {path}"
        return m.group(0)
    root = pathlib.Path(__file__).resolve().parents[2]
    assert _fn(root / "orchestrator/src/db.py") == _fn(root / "worker/src/db.py")
```

(If `test_schema_mirror.py` already has a helper that reads both db.py texts, reuse it.)

- [ ] **Step 6: Run + commit**

Run: `cd orchestrator && pytest tests/test_schema_mirror.py -v` → PASS.
```bash
git add orchestrator/src/db.py worker/src/db.py orchestrator/tests/test_cooccurrence_projection.py orchestrator/tests/test_schema_mirror.py
git commit -m "feat(graph): recompute_cooccurrence — co_occurs as a pure projection of entity_sources (mirrored)"
```

---

### Task 2: Convert the orchestrator upload paths to the projection

There are **three** `upsert_cooccurrence` writers in `ingest.py`, and the §9 "sole writer"
invariant requires converting **all** of them: the text path (`_ingest_document`, lines 134-138
and 174-180) **and** the image path (`_ingest_image`, lines 297-301). Convert both in this task.

**Files:** Modify `orchestrator/src/routes/ingest.py:134-138`, `:174-180`, `:297-301`; Test `orchestrator/tests/test_ingest_projection.py` (create).

- [ ] **Step 1: Failing test** — ingest one document via `_ingest_document`, assert its `co_occurs` rows equal a from-scratch `recompute_cooccurrence` over all entities and all have `source_chunk IS NULL`. (Use `test_store`; stub the relay/extractor via the existing test patterns in `tests/` — grep `extract_document` in tests for the established monkeypatch.)

- [ ] **Step 2: Run, expect fail** (edges still carry `source_chunk`).

- [ ] **Step 3: Implement (text path).** In `_ingest_document`, remove **both** `compute_cooccurrence_edges(...)` + `upsert_cooccurrence` loops (lines 134-138 and 174-180). Place a **single** recompute **after the domain cascade finishes** (after ~line 184) — `chunk_entities` is not fully populated until the `for domain_path` loop appends domain entities (169-171), so recomputing earlier would miss them:

```python
from ..db import recompute_cooccurrence   # add to imports
# ...after the domain-cascade loop, once chunk_entities is fully built:
affected = {eid for eids in chunk_entities.values() for eid in eids}
if affected:
    recompute_cooccurrence(store.conn, list(affected))
    store.conn.commit()
```

`store.conn` is confirmed to exist (used at ingest.py:202, 309, 325).

- [ ] **Step 4: Implement (image path).** Do the same in `_ingest_image` (lines 297-301) — it already writes `entity_sources` (line ~290), so a recompute over its entities is a drop-in replacement for the `compute_cooccurrence_edges` loop.

- [ ] **Step 5:** Now that all three sites are gone, delete the unused `compute_cooccurrence_edges` import (grep to confirm no remaining callers).

- [ ] **Step 6: Run, expect pass. Commit.**

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `refactor(ingest): upload path writes co_occurs via the projection helper`.

---

### Task 3: Convert `extract_batch` to the projection

**Files:** Modify `worker/src/jobs/extract_batch.py:150-180`; Test `worker/tests/test_extract_batch_projection.py` (create; runs in container).

- [ ] **Step 1: Failing test** — after `run_extract_batch` on a small fixture, assert every `co_occurs` row has `source_chunk IS NULL` and weights equal a from-scratch projection. (Mirror an existing `worker/tests/test_extract_batch*.py` for fixture/monkeypatch setup.)
- [ ] **Step 2: Run in container, expect fail.**
- [ ] **Step 3: Implement.** Replace the `if emits:` block's `pair_counts`/`UPDATE...weight+`/`INSERT` (lines 152-180) with, after the doc's `entity_sources` are written:

```python
from ..db import recompute_cooccurrence   # add to imports
# ...
if emits:
    affected = {eid for eids in chunk_entities.values() for eid in eids}
    if affected:
        recompute_cooccurrence(conn, list(affected))
```

(The existing `conn.commit()` at line ~184 still covers it. `emits=False` docs are unchanged — they contribute no edges.)

- [ ] **Step 4: Run in container, expect pass.**
- [ ] **Step 5: Regression** — run the full worker suite in-container (126 tests baseline, ignore `test_judge_matrix.py`). Expect no new failures. **Commit.**

---

### Task 4: Convert `SQLiteDocumentRepository.delete()` retraction

**Files:** Modify `orchestrator/src/repositories/sqlite_store.py:158-179`; Test `orchestrator/tests/test_document_delete_projection.py` (create).

- [ ] **Step 1: Failing test** — ingest 2 docs sharing an entity pair, `DELETE` one doc, assert the surviving graph equals a from-scratch projection over the remaining `entity_sources` (guards the `source_chunk` no-op the review flagged: with projection rows now `NULL`, the old `DELETE ... WHERE source_chunk IN (chunks of doc)` matches nothing).
- [ ] **Step 2: Run, expect fail** (stale inflated edges remain).
- [ ] **Step 3: Implement.** In `delete()`, remove the `source_chunk`-based DELETE at lines 160-164. Keep the `affected_entity_ids` collection (line 150-154) and the `DELETE FROM entity_sources` (156). After the orphaned-entity loop (which still hard-deletes zero-source entities and their edges), recompute for the entities that survived:

```python
from ..db import recompute_cooccurrence   # add to imports
# after the orphan loop, before the domain bookkeeping:
survivors = [e for e in affected_entity_ids if e not in entities_removed]
if survivors:
    recompute_cooccurrence(conn, survivors)
```

(Removed entities already had all their edges dropped in the orphan loop; survivors get their edges rebuilt from the now-reduced `entity_sources`.)

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `fix(delete): retract co_occurs via projection, not the now-inert source_chunk delete`.

---

### Task 5 (optional): One-time global reconciliation script

**Files:** Create `scripts/reconcile_cooccurrence.py`.

- [ ] **Step 1** Write a small driver: for a given `--db`, `recompute_cooccurrence(conn, [all active entity ids])`, commit, print counts. Idempotent. Document in the file header that it's optional (lazy per-neighborhood recompute already keeps correctness) and used only for an immediate global collapse of legacy rows after deploy.
- [ ] **Step 2** Manual smoke on a scratch copy of a real workspace DB; assert co_occurs count is stable on a second run.
- [ ] **Step 3: Commit.**

---

### Task 6 (nice-to-have): merge/rollback emit `source_chunk = NULL`

**Files:** Modify `orchestrator/src/pipeline/graph_repair.py:299-300` (and confirm `:340` rollback restores are projection-consistent).

- [ ] Make `apply_merge` insert co_occurs rows with `source_chunk = NULL` for uniformity (per spec §9 — merge/rollback stay as sanctioned corrections-path writers, but all rows should be uniformly projected). Add/adjust a test in `orchestrator/tests/` for merge co-occurrence. Run the corrections tests. **Commit.**

---

# PHASE 2 — The spine

### Task 7: Schema — `documents` columns + `watched_sources` (mirrored)

**Files:** `orchestrator/src/db.py` + `worker/src/db.py` (identical); `orchestrator/tests/test_schema_mirror.py`; test `orchestrator/tests/test_watched_sources_schema.py` (create).

- [ ] **Step 1: Failing test** — `init_db`, then assert `documents` has columns `modified_at,invalid_at,source_id`, index `idx_documents_source_path` exists, and `watched_sources` table exists with the spec §5 columns.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement in BOTH db.py:**
  - Add the `watched_sources` `CREATE TABLE` (spec §5) into the schema string, before the migration block.
  - Add `documents` columns via the idempotent ALTER pattern already used for `entities.invalid_at` (db.py ~639): guard each with a `PRAGMA table_info(documents)` column-set check, then `ALTER TABLE documents ADD COLUMN modified_at TIMESTAMP` / `invalid_at TIMESTAMP` / `source_id TEXT`.
  - Add `CREATE INDEX IF NOT EXISTS idx_documents_source_path ON documents(source_path)`.
- [ ] **Step 4: Update `test_schema_mirror.py`** — add `documents` and `watched_sources` to `_MIRRORED_TABLES`, `idx_documents_source_path` to `_MIRRORED_INDEXES`.
- [ ] **Step 5: Run both schema tests, expect pass. Commit.**

---

### Task 8: `invalid_at IS NULL` read-site sweep

**Files (enumerate + patch each):** `orchestrator/src/routes/documents.py`, `orchestrator/src/routes/reader.py`, the graph build's document/`entity_sources` joins (`orchestrator/src/pipeline/graph_snapshot.py` / `graph_v5.py`), and search (`orchestrator/src/pipeline/search/retrieval.py`). Test `orchestrator/tests/test_invalid_documents_hidden.py` (create).

- [ ] **Step 1: Failing test** — soft-delete a document (`UPDATE documents SET invalid_at=CURRENT_TIMESTAMP`), assert it does NOT appear in: `GET /documents`, `GET /documents/{id}` (404/hidden), the graph snapshot, and search results.
- [ ] **Step 2: Run, expect fail** (ghost rows surface).
- [ ] **Step 3: Implement** — add `WHERE invalid_at IS NULL` (or `AND` into existing WHEREs / JOINs) at each read site. Grep `FROM documents` and `JOIN documents` across `orchestrator/src` to find them all; patch every list/detail/join read. (Search does not thread `invalid_at` today — add it here.)
- [ ] **Step 4: Run, expect pass. Commit.**

---

### Task 9: `upsert_document` primitive (worker)

**Files:** Create `worker/src/jobs/upsert_document.py`; Test `worker/tests/test_upsert_document.py` (container).

Factor the create/update/skip/delete logic out of the existing extract flow. Signature:
```python
async def upsert_document(conn, relay, settings, *, source_path, title, content,
                          source_id=None, emits_cooccurrence=True) -> dict:
    # returns {"action": "created"|"updated"|"skipped", "document_id": ..., "entities": n}
```

Implement per spec §6–§9:
- Compute `content_hash`. Look up active doc by `source_path` with the adoption rule (spec §7 step 1: match `source_id=<this>` OR `source_id IS NULL`, else treat as new; never steal another source's path).
- **Unchanged hash** → `skipped`.
- **Update** → collect old `affected_entities`; `DELETE` old `chunks` + `entity_sources`; re-chunk/classify/extract/normalize (reuse the worker's existing classify+extract path from `extract_batch`); add new entities to `affected_entities`; `UPDATE documents ... modified_at=CURRENT_TIMESTAMP`; if `emits_cooccurrence`, `recompute_cooccurrence(conn, affected)`; `mark_graph_dirty`.
- **Create** → insert doc/chunks/entity_sources; recompute for new entities; `mark_graph_dirty`.
- Commit once at the end.

- [ ] **Step 1–5 (TDD):** tests for each branch — create returns `created` + projected edges; re-call with same content → `skipped`; re-call with changed content → `updated`, old entities gone, edges match a from-scratch projection; adoption of an `source_id IS NULL` doc at the same path (no duplicate). Run in container. **Commit per green branch.**

> This is the largest task. Keep `upsert_document` free of vault/repo specifics — it takes `content` and metadata only. The featurizers (Phase 3, Spec 2) produce those.
>
> **Factoring caveat:** the worker's classify+extract logic is currently written **inline** inside `run_extract_batch` (`worker/src/jobs/extract_batch.py`), not as a reusable function. So "reuse the worker's classify+extract path" means **extracting that inline block into a callable** (e.g. `_extract_and_store(conn, relay, settings, doc_id, chunks, emits_cooccurrence)`) as the first step of this task, then calling it from both `upsert_document` and the refactored `extract_batch` (Task 10). Budget for that extraction; don't expect a ready-made function.

---

### Task 10: `extract_batch` loops over `upsert_document`

**Files:** Modify `worker/src/jobs/extract_batch.py`; run the full worker suite as the regression guard.

- [ ] Replace the inline per-doc extract+project body with a call to `upsert_document` per doc (passing the doc's `emits_cooccurrence` from `document_collections`). The golden co-occurrence counts on a fixture repo must be unchanged. Run full worker suite in-container. **Commit.**

---

### Task 11: `watched_sources` registry route

**Files:** Create `orchestrator/src/routes/watched_sources.py`; register in `orchestrator/src/main.py` (follow the existing `include_router` pattern, e.g. how `commentary_router` was added); store helpers as needed in `sqlite_store.py`. Test `orchestrator/tests/test_watched_sources_route.py`.

- [ ] **TDD:** `POST /watched-sources` inserts a row (type, uri, cadence_hours, config_json); `GET /watched-sources` lists; `PATCH /watched-sources/{id}` toggles `enabled`/cadence. Assert via `test_client`. **Commit.**

---

### Task 12: `scan_source` job (scan → diff → act)

**Files:** Create `worker/src/jobs/scan_source.py`; wire the dispatch arm in `worker/src/main.py:106` (`elif job["type"] == "scan_source": from .jobs.scan_source import run_scan_source; await run_scan_source(job, db_path)`). Test `worker/tests/test_scan_source.py`.

Implement the spec §10 loop:
- Load the `watched_sources` row; resolve the featurizer by `type` (Phase 3 provides `vault`).
- Enumerate current `(source_path, title, content)`; apply the §6 decision table via `upsert_document`.
- Deletion set = `documents WHERE source_id=? AND invalid_at IS NULL` minus scanned paths → soft-delete each (set `invalid_at`, delete `chunks`/`entity_sources`, recompute affected, drop orphaned entities) per spec §8.
- Stamp `last_scanned_at`/`last_status`/`last_error`.

- [ ] **TDD:** a fixture "source" featurizer yielding a fixed doc set; assert create/update/skip/delete transitions and that a deleted path retracts its edges. Run in container. **Commit.**

---

### Task 13: Scheduler sweep + config field

**Files:** Modify `worker/src/config.py` + `orchestrator/src/config.py` (add `source_scan_interval_seconds: int = 900` and its `_ENV_MAP` entry `SOURCE_SCAN_INTERVAL_SECONDS`); modify `worker/src/main.py:233-241` (add a second sweep alongside the judge sweep). Test `worker/tests/test_source_sweep.py`.

- [ ] Add `import uuid` and `import json` to `worker/src/main.py` (it currently imports neither; `get_connection` is already imported at line 8).
- [ ] Add, next to the judge sweep, a `last_source_sweep` timer and:
```python
if now - last_source_sweep >= settings.source_scan_interval_seconds:
    last_source_sweep = now
    for db_path in db_paths:
        conn = get_connection(db_path)
        try:
            due = conn.execute(
                "SELECT id FROM watched_sources WHERE enabled=1 AND "
                "(last_scanned_at IS NULL OR "
                " (julianday('now') - julianday(last_scanned_at))*24 >= cadence_hours)"
            ).fetchall()
            for r in due:
                # enqueue a scan_source job in THIS db (jobs are per-workspace). The real
                # jobs table column is `config`, NOT `payload` (db.py:99-109); the worker
                # reads job["config"] (extract_batch.py:18). target = the source id.
                conn.execute("INSERT INTO jobs (id, type, target, status, config) "
                             "VALUES (?, 'scan_source', ?, 'queued', ?)",
                             (str(uuid.uuid4()), r["id"], json.dumps({"source_id": r["id"]})))
            conn.commit()
        finally:
            conn.close()
```
(Verified against the six existing `INSERT INTO jobs` sites, e.g. `sqlite_store.py:586`, `worker/src/jobs/ingest_repo.py:373`.)

- [ ] **TDD:** seed a due source, run one sweep iteration (factor the sweep into a testable function), assert a `scan_source` job is enqueued; a not-yet-due source enqueues nothing. **Commit.**

---

# PHASE 3 — Vault featurizer

### Task 14: Vault featurizer

**Files:** Create `worker/src/featurizers/vault.py`; wire into `scan_source.py`. Test `worker/tests/test_vault_featurizer.py`.

```python
from pathlib import Path

def enumerate_vault(uri: str, config: dict):
    """Yield (source_path, title, content, emits_cooccurrence) for each note."""
    exts = {("." + e.lstrip(".")).lower() for e in (config.get("ext") or [".md"])}
    root = Path(uri)
    for f in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts):
        text = f.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        yield (str(f), f.stem, text, True)   # notes are flat leaves → always emit
```

- [ ] **TDD:** a temp vault dir (`tmp_path`) with 2 `.md` + 1 empty + 1 `.txt`; assert only the 2 non-empty `.md` are yielded with correct `source_path`/`title`. **Commit.**

---

### Task 15: End-to-end vault sync

**Files:** Test `worker/tests/test_vault_sync_e2e.py` (container).

- [ ] **TDD (the acceptance test):** point a `watched_sources` row at a temp vault; run `run_scan_source`:
  1. First scan → both notes ingested; graph has projected co_occurs.
  2. Edit one note's file, re-scan → that note `updated` (new `modified_at`), stale entities gone, graph == from-scratch projection.
  3. Delete one note's file, re-scan → that doc soft-deleted (`invalid_at` set), its edges retracted, not present in `GET /documents`.
  4. Re-scan with no changes → all `skipped`, graph byte-identical.
- [ ] Run in container. **Commit.**

---

## Done criteria

- Orchestrator suite: only the 3 known pre-existing failures.
- Worker suite (in container): 126 baseline + new tests, green (ignore `test_judge_matrix.py`).
- A vault can be registered and re-synced on a cadence; new/changed/deleted notes update the graph in place; co-occurrence is a single projection with one writer.
- Spec 2 (repo featurizer) drops in behind the same `scan_source`/`upsert_document` seam — no spine changes.
