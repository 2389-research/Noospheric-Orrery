# Per-Source Silos — Phase 1 Implementation Plan (#50)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each document a **silo** (its source's stable id) and make normalization respect it — auto-merge only *within* a silo, never *across* — so identically-named entities from different corpora ("Mercury" from two repos) stay distinct, with cross-silo merges routed to the human-gated corrections flow. Delivers #50; leaves the provenance `kind`/exposure (#79) to Phase 2.

**Architecture:** A materialized `documents.silo_id` (precedence `source_id > collection_id > NULL`), populated at ingest and backfilled for existing data. **Five** entity auto-merge paths plus two internal leaks (global `merge_map`, plural collapse) become silo-aware by joining candidates through `entity_sources → documents.silo_id`. Cross-silo near-duplicates are *proposed* to `graph_issues` (by entity id), not merged. A per-silo read/viz filter closes #50's "filterable per source."

**Tech Stack:** Python 3.12, SQLite (WAL), faiss (worker normalizer), pytest. Orchestrator runs natively/CI; worker tests run in the `noospheric-orrery-worker-1` container via `uv run` (see CLAUDE.md Testing).

**Spec:** `docs/superpowers/specs/2026-08-18-source-silos-provenance-design.md` — read §3.1 (the five paths + two leaks), §5/§5.1 (data model + backfill), and the LOCKED decisions in §10 before starting.

---

## Context the executor must internalize

- **The single biggest risk (spec B1):** the dominant inline dedup is `worker/src/jobs/upsert_document.py::extract_document_entities` (used by every repo/tracker/vault ingest), NOT `normalize_entity` (loose uploads only). Scoping only the latter would leave #50 broken for the sources that matter. All five paths in §3.1 must be scoped.
- **The two leaks bypass the embedding query:** the global `merge_map` short-circuit and Tier-1 plural collapse fuse names *before* any candidate `SELECT`. Scope them too.
- **`entities` carries no silo.** An entity's silo(s) = the silo(s) of its source docs via `entity_sources → documents.silo_id`. A multi-silo entity (post an approved cross-silo merge) is expected and participates in every silo it has a source in; cross-silo *auto*-merge stays barred regardless.
- **Two `run_batch_normalization` impls, different algorithms** (`worker/src/normalizer.py` faiss vs `orchestrator/src/pipeline/embedding_normalizer.py` O(n²)) — NOT mirrored by `test_schema_mirror`. Each scoped + tested separately.
- **Schema mirror:** `documents` DDL + the `recompute_cooccurrence` helper live in both `orchestrator/src/db.py` and `worker/src/db.py` and are checked by `test_schema_mirror` — edit both identically.

## File-structure map

**Modify (schema/ingest):** `orchestrator/src/db.py`, `worker/src/db.py` (silo_id column + migration + backfill + index, both mirrored) · `worker/src/jobs/upsert_document.py` (populate silo_id on create/update) · `orchestrator/src/routes/ingest.py` (populate on the upload/text paths).
**Create:** `orchestrator/src/pipeline/silo.py` + `worker/src/silo.py` — a tiny shared helper: `resolve_silo_id(source_id, collection_id)` and the SQL fragment "entity has a source in silo S". (Two copies, mirror-tested like `classifier.py`.)
**Modify (the 5 scoping paths):** `worker/src/jobs/upsert_document.py::extract_document_entities` · `orchestrator/src/pipeline/normalizer.py::normalize_entity` · `worker/src/jobs/extract_batch_image.py` · `worker/src/normalizer.py::run_batch_normalization` · `orchestrator/src/pipeline/embedding_normalizer.py::run_batch_normalization`.
**Modify (cross-silo proposal):** reuse `orchestrator/src/pipeline/graph_repair.py::propose_correction` (+ a worker-side equivalent insert into `graph_issues`).
**Modify (reads/viz):** `orchestrator/src/pipeline/graph_v5.py` + graph snapshot (silo on nodes), entity/MCP reads, `frontend/public/viz/*` (a silo filter control).
**Tests:** one per scoping path + the two leaks + cross-silo proposal/reversal + backfill + reads.

---

### Task 1: `documents.silo_id` column, index, migration, backfill

**Files:** Modify `orchestrator/src/db.py`, `worker/src/db.py`. Test: `orchestrator/tests/test_silo_schema.py`, and `test_schema_mirror` must stay green.

- [ ] **Step 1: Failing test** — `orchestrator/tests/test_silo_schema.py`:

```python
from src.db import init_db, get_connection


def test_documents_has_silo_id_and_index(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    assert "silo_id" in cols
    idx = {r[1] for r in conn.execute("PRAGMA index_list(documents)")}
    assert any("silo" in name for name in idx)


def test_backfill_sets_silo_from_source_then_collection(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    # doc A: watched source only; doc B: collection only; doc C: both (source wins); doc D: neither
    conn.execute("INSERT INTO documents (id, title, source_id) VALUES ('A','a','src1')")
    conn.execute("INSERT INTO documents (id, title) VALUES ('B','b')")
    conn.execute("INSERT INTO collections (id, name, path, kind) VALUES ('col1','c','c','git_repo')")
    conn.execute("INSERT INTO document_collections (document_id, collection_id) VALUES ('B','col1')")
    conn.execute("INSERT INTO documents (id, title, source_id) VALUES ('C','c','src2')")
    conn.execute("INSERT INTO document_collections (document_id, collection_id) VALUES ('C','col1')")
    conn.execute("INSERT INTO documents (id, title) VALUES ('D','d')")
    conn.commit()
    from src.db import backfill_silo_ids
    backfill_silo_ids(conn)
    got = dict(conn.execute("SELECT id, silo_id FROM documents").fetchall())
    assert got == {"A": "src1", "B": "col1", "C": "src2", "D": None}
```

- [ ] **Step 2: Run → fail** (native/CI or orchestrator container):
`… pytest tests/test_silo_schema.py -q` → FAIL (no `silo_id`, no `backfill_silo_ids`).

- [ ] **Step 3: Implement in BOTH db.py.** Add to the `documents` CREATE (both files, identically — keep DDL byte-identical for `test_schema_mirror`): `silo_id TEXT` (after `source_id`). Add index `CREATE INDEX IF NOT EXISTS idx_documents_silo ON documents(silo_id);`. In each `init_db` migration block add the idempotent ALTER (mirror the #51 pattern):
```python
if "silo_id" not in cols:
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN silo_id TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
```
Add a shared `backfill_silo_ids(conn)` (define in both db.py, mirror-tested — or in `silo.py` from Task 2 and call it):
```python
def backfill_silo_ids(conn) -> int:
    # source_id wins; else the doc's collection membership; else NULL. Only fills NULLs.
    conn.execute("UPDATE documents SET silo_id = source_id "
                 "WHERE silo_id IS NULL AND source_id IS NOT NULL")
    conn.execute("""UPDATE documents SET silo_id = (
                        SELECT dc.collection_id FROM document_collections dc
                        WHERE dc.document_id = documents.id LIMIT 1)
                     WHERE silo_id IS NULL AND source_id IS NULL
                       AND EXISTS (SELECT 1 FROM document_collections dc2 WHERE dc2.document_id = documents.id)""")
    conn.commit()
    return conn.total_changes
```
Call `backfill_silo_ids(conn)` once inside `init_db` **after** the ALTERs (idempotent — only fills NULLs), so existing noospheres migrate on next boot (§5.1).

- [ ] **Step 4: Run → pass**, and run `test_schema_mirror` (native/CI) to confirm the two `documents` DDLs + any mirrored helper stayed identical.
- [ ] **Step 5: Commit** — `feat(schema): documents.silo_id + index + backfill (both mirrors) (#50)`.

---

### Task 2: Populate `silo_id` at ingest + the shared silo helper

**Files:** Create `orchestrator/src/pipeline/silo.py`, `worker/src/silo.py` (mirror pair). Modify `worker/src/jobs/upsert_document.py` (INSERT/UPDATE), `orchestrator/src/routes/ingest.py::_ingest_document` (INSERT). Test: `worker/tests/test_silo_populate.py`.

- [ ] **Step 1: Failing test** — ingest a doc with `source_id='v1'` (no collection) → its `documents.silo_id == 'v1'`; a repo doc with both source_id + collection → silo_id == source_id; a loose upload → silo_id IS NULL. (Follow `test_upsert_document.py`'s FakeRelay + tmp DB pattern; assert on the stored row.)

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement.** In `silo.py` (both copies):
```python
def resolve_silo_id(source_id, collection_id):
    """Precedence: source_id > collection_id > None (spec §5)."""
    return source_id or collection_id or None

# SQL fragment: entities having at least one source in silo :silo (NULL-safe).
SILO_MATCH = ("EXISTS (SELECT 1 FROM entity_sources es JOIN documents d ON d.id = es.document_id "
              "WHERE es.entity_id = e.id AND d.silo_id IS :silo)")   # see Task 4 for exact binding
```
In `upsert_document` INSERT and UPDATE, set `silo_id = resolve_silo_id(source_id, collection_id)` (the function already receives `source_id`; `collection_id` is the param it already accepts). In `_ingest_document`, pass `silo_id=None` (loose uploads) — or the caller's if a future ingest path supplies one.

- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(sync): populate documents.silo_id at ingest + shared silo helper (#50)`.

---

### Task 3: Silo-scope `extract_document_entities` — the PRIMARY inline path (the #50 crux)

**Files:** Modify `worker/src/jobs/upsert_document.py::extract_document_entities`. Test: `worker/tests/test_silo_scope_inline.py`.

- [ ] **Step 1: Failing test.** Two silos, each ingesting a doc that mentions the same entity name → **two** distinct `entities` rows. Same name within one silo → **one**. (Run through `extract_document_entities` with a FakeRelay that returns the same entity for both; assert entity count per silo.)

- [ ] **Step 2: Run → fail** (today it merges to one — the bug).

- [ ] **Step 3: Implement.** `extract_document_entities` knows its `doc_id`; derive the doc's silo once at the top:
```python
silo = conn.execute("SELECT silo_id FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
```
Replace the two global lookups (`worker/src/jobs/upsert_document.py` ~L96-105):
- **merge_map short-circuit** — honor a hit only if the aliased target has a source in `silo` (spec §3.1 merge_map rule):
```python
row = conn.execute(
    "SELECT mm.to_entity_id FROM merge_map mm "
    "WHERE mm.from_name = ? AND EXISTS ("
    "  SELECT 1 FROM entity_sources es JOIN documents d ON d.id = es.document_id "
    "  WHERE es.entity_id = mm.to_entity_id AND d.silo_id IS ?)", (name, silo)).fetchone()
```
  (`d.silo_id IS ?` binds NULL correctly for the null pool.)
- **exact canonical lookup** — require a source in `silo`:
```python
row = conn.execute(
    "SELECT e.id FROM entities e WHERE e.canonical_name = ? AND e.type = ? AND EXISTS ("
    "  SELECT 1 FROM entity_sources es JOIN documents d ON d.id = es.document_id "
    "  WHERE es.entity_id = e.id AND d.silo_id IS ?)", (name, etype, silo)).fetchone()
```
When neither matches, a **new** entity is created (existing behaviour) — now correctly per-silo.

- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(silo): scope extract_document_entities (merge_map + canonical) by silo (#50)`.

---

### Task 4: Silo-scope `normalize_entity` (loose-upload inline path)

**Files:** Modify `orchestrator/src/pipeline/normalizer.py::normalize_entity`. Test: `orchestrator/tests/test_silo_scope_normalize_entity.py`.

- [ ] Steps mirror Task 3, but this path serves the `silo_id IS NULL` pool (loose uploads). `normalize_entity(store_or_conn, name, entity_type)` gains the caller's silo (thread a `silo=None` param from `_ingest_document`, default `None` for back-compat). Apply the same merge_map + canonical silo predicates. **Test:** two null-silo docs with the same name still merge (regression — today's behaviour); a null-silo name does **not** merge onto a *siloed* entity of the same name. Commit.

---

### Task 5: Silo-scope `extract_batch_image` (image inline fuse — spec N1)

**Files:** Modify `worker/src/jobs/extract_batch_image.py` (~L117). Test: `worker/tests/test_silo_scope_image.py`.

- [ ] Same canonical-lookup fix as Task 3, keyed on the image doc's `silo_id`. Test: two silos, same image-entity name → distinct. (Latent today since images arrive null-silo, but scope it so it can't leak — spec §3.1 path 5.) Commit.

---

### Task 6: Silo-partition the worker faiss batch normalizer + propose cross-silo

**Files:** Modify `worker/src/normalizer.py::run_batch_normalization`. Test: `worker/tests/test_silo_scope_batch_faiss.py`.

- [ ] **Step 1: Failing test.** Seed two silos with the same-named entity (distinct ids, sources in different silos) + high embedding similarity → batch run leaves them **distinct** AND files a `graph_issues` proposal (action=merge, the two ids). Same silo, similar names → auto-merged. A cross-silo plural pair (`agents`/`agent`) → **not** collapsed.

- [ ] **Step 2: Run → fail** (today: global merge).

- [ ] **Step 3: Implement.** (a) **Plural collapse** — restrict the global `all_names`/`get_by_name` fuse to same-silo names. (b) **faiss candidate search** — widen the grouping key from `type` to `(type, silo)`: build the per-`(type, silo)` `IndexFlatIP` from entities filtered to that silo (join `entity_sources → documents.silo_id`; a multi-silo entity appears in each of its silos' groups). (c) **Cross-silo detection** — when a high-similarity pair spans silos (compute each entity's silo-set; disjoint or null-vs-nonnull), do NOT merge; insert a pending `graph_issues` row (mirror `graph_repair.propose_correction`'s insert, `action="merge"`, `target_entity_id`/`target_b_entity_id` = the two **ids**, rationale=similarity). Any cross-silo pair — auto-band or review-band — goes to `graph_issues`, never `normalization_review_queue`.

- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(silo): partition worker faiss normalization by (type, silo); propose cross-silo (#50)`.

---

### Task 7: Silo-scope the orchestrator O(n²) batch normalizer + propose cross-silo

**Files:** Modify `orchestrator/src/pipeline/embedding_normalizer.py::run_batch_normalization` (both `_run_batch_store`/`_run_batch_conn`). Test: `orchestrator/tests/test_silo_scope_batch_nested.py`.

- [ ] Same behaviour as Task 6 for the **different** (nested-loop, no faiss) algorithm: plural collapse + the all-pairs comparison restricted to same-silo; cross-silo similars → `graph_issues` proposal by id. Separate test (this impl is not a mirror of the worker's — spec §3.1). Commit.

---

### Task 8: Cross-silo merge via corrections round-trips (reuse, verify)

**Files:** Test only — `orchestrator/tests/test_cross_silo_merge_roundtrip.py`. (No new correction code — reuse `graph_repair.apply_merge` / `rollback_merge`.)

- [ ] **Step 1: Test.** Given a proposed cross-silo merge in `graph_issues`, approving it (`resolve_correction`/`apply_merge`) merges the two entities (survivor now has sources in both silos); `rollback_merge` reverses it cleanly (both entities distinct again, edges restored). Assert the survivor's post-merge multi-silo membership is what the scoping queries then see (Task 6/7 multi-silo rule).
- [ ] **Step 2–3: Run → pass** (should pass against existing corrections code; if not, the gap is a real finding — surface it). **Commit.**

---

### Task 9: Expose silo in reads + a per-silo viz/query filter (closes #50's "filterable")

**Files:** Modify `orchestrator/src/pipeline/graph_v5.py` (+ snapshot), entity read routes, `orchestrator/src/mcp_server.py` (annotate nodes with silo), `frontend/public/viz/*` (filter control). Test: `orchestrator/tests/test_graph_silo_filter.py`.

- [ ] **Step 1: Failing test.** `GET /graph` nodes carry their `silo_id`; a `?silo=<id>` filter returns only that silo's nodes/edges (and unsiloed with `?silo=none` or similar). `get_entity` sources annotate silo.
- [ ] **Step 2–4: Implement** the silo on nodes + a filter param on the graph read; add a viz filter control (verify per CLAUDE.md canvas rules — drive a browser + screenshot). **Note:** `kind` exposure is Phase 2; this task exposes **silo id/filter only**, which is what #50's acceptance requires.
- [ ] **Step 5: Commit.**

---

### Task 10: Full suite, live acceptance, docs, close #50

- [ ] **Step 1:** Run the full orchestrator suite (native/CI) and the full worker suite (container) — all green (minus the documented pre-existing deselects). Confirm `test_schema_mirror` green.
- [ ] **Step 2: Live acceptance** (rebuild stack; the #41/#51 loop). Register **two sample git repos/orgs + one sample Obsidian vault** as distinct silos; ingest each; verify: an identically-named entity stays two nodes across silos, `GET /graph`/viz filters per silo, a deliberate cross-silo merge via corrections applies and reverses. Use **freshly-ingested** silos for distinctness (not the backfilled blend — §5.1).
- [ ] **Step 3: Docs** — note the silo model + backfill in `docs/graph-corrections.md` (cross-silo proposals now a source of merge proposals) and wherever ingestion is documented.
- [ ] **Step 4: PR + close #50.** Push; open the PR (do NOT merge without human go-ahead). Note Phase 2 (#79 `kind` + emission + kind-exposure) follows as a separate plan/PR.

---

## Definition of done
- All five auto-merge paths + the two leaks are silo-scoped, each with a passing test; a test that only checked the faiss query would NOT be sufficient (spec §8).
- Cross-silo similars produce `graph_issues` proposals (by id), not merges; approve+rollback round-trips.
- `documents.silo_id` materialized, indexed, backfilled; `test_schema_mirror` green (both db.py identical).
- Null-silo (loose upload) normalization behaviour unchanged (regression test).
- `GET /graph`/viz filter per silo (closes #50's filterable half).
- Live acceptance walked on two git repos + a vault; #50 closeable; #79 (kind/exposure) explicitly deferred to Phase 2.
