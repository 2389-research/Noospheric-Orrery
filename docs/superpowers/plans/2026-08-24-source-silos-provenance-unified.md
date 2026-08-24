# Per-Source Silos + Provenance — Unified Implementation Plan (#50 + #79)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each document a **silo** (its source's stable id) and a **provenance `kind`** (its epistemic nature), both set by the ingestion flow at the same moment. Normalization respects the silo — auto-merge only *within* a silo, never *across* (cross-silo near-duplicates route to the human-gated corrections flow). The `kind` gates co-occurrence emission for opinion sources and is surfaced in every agent read, so a consuming agent can tell "what the code does" from "what an agent thinks." Delivers **#50 and #79 together** — they are one feature (the ingestion flow determines both), built scoping-first then exposure.

**Architecture:** A materialized `documents.silo_id` (precedence `source_id > collection_id > NULL`) and a materialized `documents.provenance_kind` (resolved at ingest from a per-featurizer flow default, overridable via `watched_sources.config_json` / an ingest arg), both populated at ingest and backfilled. **Five** entity auto-merge paths plus two internal leaks (global `merge_map`, plural collapse) become silo-aware by joining candidates through `entity_sources → documents.silo_id`. Cross-silo near-duplicates are *proposed* to `graph_issues` (by entity id), not merged. `recompute_cooccurrence` (both `db.py`) additionally suppresses edges from gated `kind`s. Silo + kind ride along in `GET /graph`, entity reads, the MCP read tools, and a viz filter.

**Tech Stack:** Python 3.12, SQLite (WAL), faiss (worker normalizer), pytest, Next.js/Canvas2D (viz). Orchestrator tests run natively/CI; worker tests run in the `noospheric-orrery-worker-1` container via `uv run` (see CLAUDE.md → Testing).

**Spec:** `docs/superpowers/specs/2026-08-18-source-silos-provenance-design.md` — read §3.1 (the five paths + two leaks), §4/§4.1 (`kind` + emission), §5/§5.1 (data model + backfill), §6 (exposure), and the LOCKED decisions in §10 before starting.

---

## Context the executor must internalize

- **The single biggest risk (spec B1):** the dominant inline dedup is `worker/src/jobs/upsert_document.py::extract_document_entities` (used by every repo/tracker/vault ingest), NOT `normalize_entity` (loose uploads only). Scoping only the latter would leave #50 broken for the sources that matter. **All five paths in §3.1 must be scoped.**
- **The two leaks bypass the embedding query:** the global `merge_map` short-circuit and Tier-1 plural collapse fuse names *before* any candidate `SELECT`. Scope them too.
- **`entities` carries no silo.** An entity's silo(s) = the silo(s) of its source docs via `entity_sources → documents.silo_id`. A multi-silo entity (post an approved cross-silo merge) is expected and participates in every silo it has a source in; cross-silo *auto*-merge stays barred regardless.
- **Two `run_batch_normalization` impls, different algorithms** (`worker/src/normalizer.py` faiss vs `orchestrator/src/pipeline/embedding_normalizer.py` O(n²)) — NOT mirrored by `test_schema_mirror`. Each scoped + tested separately.
- **Schema mirror:** `documents` DDL, the `recompute_cooccurrence` helper, and the mirrored index list live in both `orchestrator/src/db.py` and `worker/src/db.py` and are checked by `test_schema_mirror` — edit both identically, and add new indexes/tables to the mirror lists.
- **⚠️ CRITICAL — the two orchestrator normalization paths run through the REPOSITORY layer, not raw SQL.** `normalize_entity(store, …)` (`normalizer.py`, the `_ingest_document` production path) and `run_batch_normalization(store)` (`embedding_normalizer.py::_run_batch_store`, the `/normalize` route path) fuse entities via repository methods — `store.normalization.get_merge_map_entry()`, `store.entities.get_by_name()`, `store.entities.get_all_for_normalization()` (`repositories/sqlite_store.py`; `interfaces.py`) — **which take no silo argument.** Each of those functions ALSO has a legacy raw-`sqlite3.Connection` branch; production does NOT use it. So **Tasks 4 & 7 must add silo-aware repository methods and test against the STORE path**, or you get green tests (raw branch) with broken production (store branch). The worker paths (Task 3 `extract_document_entities`, Task 6 `worker/src/normalizer.py`) DO use raw `conn` directly — raw SQL is correct there.
- **`kind` is materialized on `documents` for the same reason `silo_id` is** — the two consumers (`recompute_cooccurrence` emission gating; the read layer) both work at the document/entity-source level, so a materialized `documents.provenance_kind` gives a simple hot join, exactly parallel to `silo_id`. The **source of truth** stays at the source/flow level (featurizer default + `config_json` override); the document column is the resolved, materialized copy. **Do NOT overload `collections.kind`** (which already means the collection *type*: `git_repo`/`tracker_run`) as the provenance vocabulary — map from it in code instead. See the note in Task 9. *(This interpretation reconciles a tension in the spec between §4.1 "override in config_json" and §10.2 "kind column on the row"; a plan reviewer should confirm.)*
- **Only one kind is gated by default.** Per spec §4 the emission table reduces to: `neutral_summary` leaf emits (rollup already suppressed by the existing membership gate), `human_vault` emits, `human_reviewed` emits, **`agent_report` suppressed.** So the kind-level emission rule is a single predicate `provenance_kind != 'agent_report'`, AND-combined with the existing membership gate. Keep it expressed so it generalizes to a kind→emits map later.

## File-structure map

**Modify (schema/ingest):** `orchestrator/src/db.py`, `worker/src/db.py` (silo_id + provenance_kind columns + migrations + backfill + index, both mirrored) · `worker/src/jobs/upsert_document.py` (populate both on create/update) · `orchestrator/src/routes/ingest.py` (populate on the upload/text paths).
**Create:** `orchestrator/src/pipeline/silo.py` + `worker/src/silo.py` — a tiny shared helper: `resolve_silo_id(source_id, collection_id)`, `resolve_kind(flow_default, override)`, the flow-default map, and the SQL fragment "entity has a source in silo S". (Two copies, mirror-tested like `classifier.py`.)
**Modify (the 5 scoping paths):** `worker/src/jobs/upsert_document.py::extract_document_entities` (raw conn) · `orchestrator/src/pipeline/normalizer.py::normalize_entity` (**store branch**) · `worker/src/jobs/extract_batch_image.py` (raw conn) · `worker/src/normalizer.py::run_batch_normalization` (raw conn, faiss) · `orchestrator/src/pipeline/embedding_normalizer.py::run_batch_normalization` (**store branch, `_run_batch_store`**).
**Modify (repository layer — Finding 2):** `orchestrator/src/repositories/sqlite_store.py` + `orchestrator/src/repositories/interfaces.py` — add silo-aware `get_by_name`, `get_merge_map_entry`, `get_all_for_normalization`.
**Modify (cross-silo proposal):** reuse `orchestrator/src/pipeline/graph_repair.py::propose_correction` (+ a worker-side equivalent insert into `graph_issues`).
**Modify (emission):** `recompute_cooccurrence` in BOTH `db.py` (AND the kind gate onto the existing membership gate).
**Modify (reads/viz):** `orchestrator/src/pipeline/graph_v5.py` + graph snapshot (silo + kind on nodes), entity/MCP reads, `frontend/public/viz/*` (a silo/kind filter control).
**Tests:** one per scoping path + the two leaks + cross-silo proposal/reversal + backfill + emission + reads.

---

## PART A — Silos (#50): scope normalization by source

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
    # doc A: watched source only; B: collection only; C: both (source wins); D: neither
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

- [ ] **Step 3: Implement in BOTH db.py.** Add `silo_id TEXT` to the `documents` CREATE (both files, byte-identical for `test_schema_mirror`), after `source_id`. Add `CREATE INDEX IF NOT EXISTS idx_documents_silo ON documents(silo_id);` in both. **Add `"idx_documents_silo"` to `_MIRRORED_INDEXES`** in `test_schema_mirror.py` (Finding 5; the `documents` table is already in `_MIRRORED_TABLES`). In each `init_db` migration block add the idempotent ALTER (mirror the #51 pattern):
```python
if "silo_id" not in cols:
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN silo_id TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
```
Add a shared `backfill_silo_ids(conn)` (both db.py, mirror-tested):
```python
def backfill_silo_ids(conn) -> int:
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

- [ ] **Step 4: Run → pass**, and run `test_schema_mirror` (native/CI) to confirm both `documents` DDLs stayed identical.
- [ ] **Step 5: Commit** — `feat(schema): documents.silo_id + index + backfill (both mirrors) (#50)`.

---

### Task 2: Populate `silo_id` at ingest + the shared silo helper

**Files:** Create `orchestrator/src/pipeline/silo.py`, `worker/src/silo.py` (mirror pair). Modify `worker/src/jobs/upsert_document.py` (INSERT/UPDATE), `orchestrator/src/routes/ingest.py::_ingest_document` (INSERT). Test: `worker/tests/test_silo_populate.py`.

- [ ] **Step 1: Failing test** — ingest a doc with `source_id='v1'` (no collection) → `documents.silo_id == 'v1'`; a repo doc with both source_id + collection → silo_id == source_id; a loose upload → silo_id IS NULL. (Follow `test_upsert_document.py`'s FakeRelay + tmp DB pattern; assert on the stored row.)

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement.** In `silo.py` (both copies):
```python
def resolve_silo_id(source_id, collection_id):
    """Precedence: source_id > collection_id > None (spec §5)."""
    return source_id or collection_id or None


# SQL fragment: <entity_col> has at least one source in the silo bound to a POSITIONAL ? (NULL-safe).
# Positional `?` everywhere (Finding 6 — sqlite raises if one statement mixes named + numbered params).
def silo_match(entity_col: str) -> str:
    return (f"EXISTS (SELECT 1 FROM entity_sources es JOIN documents d ON d.id = es.document_id "
            f"WHERE es.entity_id = {entity_col} AND d.silo_id IS ?)")
```
In `upsert_document` INSERT and UPDATE, set `silo_id = resolve_silo_id(source_id, collection_id)`. In `_ingest_document`, pass `silo_id=None` (loose uploads).

- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(sync): populate documents.silo_id at ingest + shared silo helper (#50)`.

---

### Task 3: Silo-scope `extract_document_entities` — the PRIMARY inline path (the #50 crux)

**Files:** Modify `worker/src/jobs/upsert_document.py::extract_document_entities`. Test: `worker/tests/test_silo_scope_inline.py`.

- [ ] **Step 1: Failing test.** Two silos, each ingesting a doc that mentions the same entity name → **two** distinct `entities` rows. Same name within one silo → **one**. (Run through `extract_document_entities` with a FakeRelay that returns the same entity for both; assert entity count per silo.)

- [ ] **Step 2: Run → fail** (today it merges to one — the bug).

- [ ] **Step 3: Implement.** Derive the doc's silo once at the top:
```python
silo = conn.execute("SELECT silo_id FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
```
Replace the two global lookups (~L96-105):
- **merge_map short-circuit** — honor a hit only if the aliased target has a source in `silo`:
```python
row = conn.execute(
    "SELECT mm.to_entity_id FROM merge_map mm "
    "WHERE mm.from_name = ? AND EXISTS ("
    "  SELECT 1 FROM entity_sources es JOIN documents d ON d.id = es.document_id "
    "  WHERE es.entity_id = mm.to_entity_id AND d.silo_id IS ?)", (name, silo)).fetchone()
```
- **exact canonical lookup** — require a source in `silo`:
```python
row = conn.execute(
    "SELECT e.id FROM entities e WHERE e.canonical_name = ? AND e.type = ? AND EXISTS ("
    "  SELECT 1 FROM entity_sources es JOIN documents d ON d.id = es.document_id "
    "  WHERE es.entity_id = e.id AND d.silo_id IS ?)", (name, etype, silo)).fetchone()
```
(`d.silo_id IS ?` binds NULL correctly for the null pool.) When neither matches, a **new** entity is created — now correctly per-silo.

- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(silo): scope extract_document_entities (merge_map + canonical) by silo (#50)`.

---

### Task 4: Silo-scope `normalize_entity` — via the REPOSITORY layer (the production path, Finding 2)

**Files:** Modify `orchestrator/src/repositories/interfaces.py` + `orchestrator/src/repositories/sqlite_store.py` (`get_by_name`, `get_merge_map_entry`), `orchestrator/src/pipeline/normalizer.py::normalize_entity` (thread silo), `orchestrator/src/routes/ingest.py::_ingest_document` (pass silo). Test: `orchestrator/tests/test_silo_scope_normalize_entity.py` — **written against the store path** (`test_store` fixture).

- [ ] **Step 1: Failing test (store path).** With a `test_store`: create a siloed entity "mercury" (a doc with `silo_id='v1'` + its `entity_sources`); then `normalize_entity(store, "mercury", "Concept", silo=None)` (a loose upload) must create a **NEW** entity, not fuse onto the 'v1' one. Separately, two null-silo mentions of "mercury" still fuse (regression).
- [ ] **Step 2: Run → fail** — today `store.entities.get_by_name(...)` returns the 'v1' entity regardless of silo.
- [ ] **Step 3: Implement.** Add an optional `silo` param to `EntityRepository.get_by_name` and `NormalizationRepository.get_merge_map_entry` (interfaces + sqlite_store). When `silo` is passed, AND the existing query with the `silo_match` EXISTS clause (positional `?`, NULL-safe); back-compat (no silo) when omitted. Thread `silo` through `normalize_entity(store_or_conn, name, entity_type, silo=None)` ← `_ingest_document` (loose upload → `None`). Scope BOTH the merge_map short-circuit and `get_by_name`.
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(silo): scope normalize_entity via silo-aware repository methods (#50)`.

---

### Task 5: Silo-scope `extract_batch_image` (image inline fuse — spec N1)

**Files:** Modify `worker/src/jobs/extract_batch_image.py` (~L117). Test: `worker/tests/test_silo_scope_image.py`.

- [ ] Same canonical-lookup fix as Task 3, keyed on the image doc's `silo_id`. Test: two silos, same image-entity name → distinct. (Latent today since images arrive null-silo, but scope it so it can't leak — spec §3.1 path 5.) Commit — `feat(silo): scope image inline fuse by silo (#50)`.

---

### Task 6: Silo-partition the worker faiss batch normalizer + propose cross-silo

**Files:** Modify `worker/src/normalizer.py::run_batch_normalization`. Test: `worker/tests/test_silo_scope_batch_faiss.py`.

- [ ] **Step 1: Failing test.** Two silos with the same-named entity (distinct ids, sources in different silos) + high embedding similarity → batch run leaves them **distinct** AND files a `graph_issues` proposal (action=merge, the two ids). Same silo, similar names → auto-merged. A cross-silo plural pair (`agents`/`agent`) → **not** collapsed.
- [ ] **Step 2: Run → fail** (today: global merge).
- [ ] **Step 3: Implement.** **Keep the existing per-`type` `IndexFlatIP` — do NOT partition the index by silo (Finding 3):** a strict `(type, silo)` index means cross-silo pairs never share a group, so their similarity is never computed and the cross-silo proposal below becomes unreachable. Instead, for each high-similarity candidate pair the per-type search surfaces, compute each entity's **silo-set** (`entity_sources → documents.silo_id`, may be multi-valued) and branch:
   - **overlapping/shared silo (incl. both null)** → auto-merge, as today;
   - **disjoint (or null-vs-non-null)** → do NOT merge; insert a pending `graph_issues` row. The worker **cannot import `graph_repair`** (separate package), so it does its own insert matching the `graph_issues` DDL: `action='merge'`, `target_entity_id`+`target_entity_name`, `target_b_entity_id`+`target_b_name`, rationale=similarity, keyed on **ids**. Any cross-silo pair → `graph_issues`, never `normalization_review_queue`.
   - **Plural collapse** (the pre-faiss stage) — restrict its global `all_names`/`get_by_name` fuse to same-silo names too.
- [ ] **Step 3b: Add `"graph_issues"` to `_MIRRORED_TABLES`** (`test_schema_mirror.py`) — Task 6 makes the **worker** a writer of `graph_issues` (Finding 4). Confirm both `db.py` `graph_issues` DDLs are identical.
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(silo): silo-aware worker faiss normalization; propose cross-silo to graph_issues (#50)`.

---

### Task 7: Silo-scope the orchestrator O(n²) batch normalizer — via the STORE path + propose cross-silo

**Files:** Modify `orchestrator/src/repositories/sqlite_store.py::get_all_for_normalization` (silo-aware), `orchestrator/src/pipeline/embedding_normalizer.py::_run_batch_store`. Test: `orchestrator/tests/test_silo_scope_batch_nested.py` — **against the store path** (`test_store` fixture).

- [ ] Same behaviour as Task 6 for this **different** (nested-loop, no faiss) algorithm, but through the repository: `get_all_for_normalization` returns each entity with its silo-set (or the all-pairs loop joins to it); plural collapse + all-pairs comparison auto-merge only same-silo; cross-silo similars → `graph_issues` proposal by id — **reuse `graph_repair.propose_correction` here** (the orchestrator CAN import it). **Do not regress:** `get_all_for_normalization` currently doesn't filter `invalid_at` — preserve that while adding the silo join. Commit — `feat(silo): silo-aware orchestrator batch normalization via store path (#50)`.

---

### Task 8: Cross-silo merge via corrections round-trips (reuse, verify)

**Files:** Test only — `orchestrator/tests/test_cross_silo_merge_roundtrip.py`. (No new correction code — reuse `graph_repair.apply_merge` / `rollback_merge`.)

- [ ] **Step 1: Test.** Given a proposed cross-silo merge in `graph_issues`, approving it (`resolve_correction`/`apply_merge`) merges the two entities (survivor now has sources in both silos); `rollback_merge` reverses it cleanly (both distinct again, edges restored). Assert the survivor's post-merge multi-silo membership is what the scoping queries (Task 6/7) then see (multi-silo rule).
- [ ] **Step 2–3: Run → pass** (should pass against existing corrections code; if not, the gap is a real finding — surface it). **Commit.**

---

## PART B — Provenance `kind` (#79): tag, gate emission, expose

### Task 9: Provenance `kind` — flow default + override + materialize on `documents` + backfill

**Files:** Modify `orchestrator/src/db.py`, `worker/src/db.py` (add `provenance_kind`, migration, backfill, mirror). Extend `orchestrator/src/pipeline/silo.py` + `worker/src/silo.py` (`resolve_kind` + the flow-default map). Modify `worker/src/jobs/upsert_document.py` + `orchestrator/src/routes/ingest.py` (set it at ingest). Test: `orchestrator/tests/test_provenance_kind.py`, `worker/tests/test_kind_populate.py`.

- [ ] **Step 1: Failing tests.**
  - `resolve_kind`: `resolve_kind("neutral_summary", None) == "neutral_summary"`; override wins: `resolve_kind("neutral_summary", "agent_report") == "agent_report"`; unknown override rejected (falls back to default or raises — pick and assert).
  - Schema: `documents` has `provenance_kind`; a vault ingest → `human_vault`; a codesum/tracksum repo ingest → `neutral_summary`; a loose upload → default (`neutral_summary` or `NULL` — decide; recommend `NULL` = "unknown", treated as ungated non-agent so it emits). Assert on the stored `documents.provenance_kind`.
  - Backfill: existing collections (`kind='git_repo'`/`'tracker_run'`) → `neutral_summary`; existing vault `watched_sources` (`type='vault'`) → `human_vault`; existing repo sources → `neutral_summary`.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement.**
  - **Vocabulary + defaults in `silo.py` (both copies)** — the 4 LOCKED kinds and the flow-default map:
    ```python
    KINDS = {"neutral_summary", "human_vault", "agent_report", "human_reviewed"}

    # Flow default keyed by featurizer / source type (spec §4.1 point 1).
    FLOW_DEFAULT_KIND = {
        "vault": "human_vault",
        "repo": "neutral_summary", "git_repo": "neutral_summary",
        "tracker": "neutral_summary", "tracker_run": "neutral_summary",
        "codesum": "neutral_summary", "tracksum": "neutral_summary",
    }

    def resolve_kind(flow_default, override=None):
        """override (from watched_sources.config_json / ingest arg) wins; else flow default."""
        if override in KINDS:
            return override
        return flow_default  # a valid kind, or None for loose uploads
    ```
  - **DO NOT overload `collections.kind`** (it holds the collection *type* `git_repo`/`tracker_run`). Derive the flow default from it via `FLOW_DEFAULT_KIND`, and from `watched_sources.type` for watched sources. The **override** lives in `watched_sources.config_json` (per spec §4.1; same place #41 put `ext`/`ignore`) and, for collection-only one-shot ingests, an optional `kind=` arg on the ingest call.
  - **Materialize** `documents.provenance_kind TEXT` (both db.py, mirrored; idempotent ALTER like Task 1) — resolved at ingest (`upsert_document`, `_ingest_document`) via `resolve_kind(flow_default, override)`, exactly parallel to `silo_id`.
  - **Backfill** `backfill_provenance_kind(conn)` (both db.py, mirror-tested), called in `init_db` after the ALTER: fill NULLs from each doc's silo owner — `collections.kind`/`watched_sources.type` → `FLOW_DEFAULT_KIND`; loose/directory docs stay `NULL`. Idempotent.
- [ ] **Step 4: Run → pass; `test_schema_mirror` green.** Commit — `feat(provenance): documents.provenance_kind — flow default + config_json override + backfill (#79)`.

---

### Task 10: Gate co-occurrence emission by `kind` (`recompute_cooccurrence`, both db.py)

**Files:** Modify `recompute_cooccurrence` in BOTH `orchestrator/src/db.py` and `worker/src/db.py` (mirrored). Test: `orchestrator/tests/test_kind_emission.py`.

- [ ] **Step 1: Failing test.** Two docs in an `agent_report` silo that co-mention entities A,B → after `recompute_cooccurrence`, **no A–B edge** (or its weight excludes the agent_report contribution). The same two docs as a `human_vault` (or `neutral_summary` leaf) silo → the A–B edge **is** present. Critically exercise the **non-`document_collections` path** (a watched *vault* silo with no membership row — spec B6), since that's the case the old `document_collections.emits_cooccurrence` lever could not reach.
- [ ] **Step 2: Run → fail** (today agent_report docs emit edges).
- [ ] **Step 3: Implement.** Add a kind predicate to the emission filter, **AND-combined** with the existing membership gate so both suppressors work independently (spec §4):
  - existing gate: a doc emits iff `COALESCE(MIN(document_collections.emits_cooccurrence), 1) = 1` (rollup docs suppressed).
  - new gate: `AND COALESCE(documents.provenance_kind, '') != 'agent_report'`.
  Express it so it generalizes to a kind→emits map (a `CASE` or a small joined lookup) rather than hard-coding one string in three places if it appears more than once. Mirror the change in both `db.py`; the subquery parallels the existing `MIN(document_collections.emits_cooccurrence)` one.
- [ ] **Step 4: Run → pass; `test_schema_mirror` green (both `recompute_cooccurrence` identical).** Commit — `feat(provenance): gate co-occurrence emission for agent_report silos (#79)`.

---

### Task 11: Expose silo + kind in reads, MCP, and viz (closes #50's "filterable" + #79's exposure)

**Files:** Modify `orchestrator/src/pipeline/graph_v5.py` (+ snapshot builder), entity read routes, `orchestrator/src/mcp_server.py` (annotate nodes/sources), `orchestrator/src/routes/graph.py` (`?silo=`/`?kind=` post-filter), `frontend/public/viz/*` (filter control). Test: `orchestrator/tests/test_graph_silo_filter.py`, `orchestrator/tests/test_reads_expose_provenance.py`.

- [ ] **Step 1: Failing tests.**
  - `GET /graph` nodes carry `silo_id` **and** `provenance_kind`; `?silo=<id>` returns only that silo's nodes/edges (`?silo=none` for the null pool); `?kind=<k>` filters by kind.
  - `get_entity` sources annotate silo + kind; `search_knowledge_graph` / `get_neighborhood` / `get_subgraph` (MCP, the #48 read path) include silo + kind on nodes; document reads include the doc's silo + kind.
- [ ] **Step 2–4: Implement (mind the cached snapshot — Finding 7).** `GET /graph` serves a **materialized snapshot** via `get_or_build` (`routes/graph.py`, `graph_snapshot.py`), not a live query. So: (a) attach node `silo_id` + `provenance_kind` in the **snapshot builder** `graph_v5.build_graph_v5(store, …)` (it reads through the repository layer — add both to the entity/doc rows it already fetches); (b) apply `?silo=`/`?kind=` as a **post-filter over the loaded payload** in the route (snapshot stays whole/cached). Annotate silo+kind in the entity/MCP/document reads. Add a viz filter control (silo + kind) — **verify per CLAUDE.md canvas rules: drive a browser + screenshot + model-judge; Canvas2D can't be DOM-inspected;** use `window.__viz` hooks in the galaxy view.
- [ ] **Step 5: Commit** — `feat(provenance): expose silo + kind in graph/entity/MCP reads + viz filter (#50, #79)`.

---

## PART C — Verify & ship

### Task 12: Full suite, live acceptance (both issues), docs, close #50 + #79

- [ ] **Step 1:** Run the full orchestrator suite (native/CI) and the full worker suite (container, `uv run`) — all green (minus the documented pre-existing deselects). `test_schema_mirror` green.
- [ ] **Step 2: Live acceptance** (rebuild stack; the #41/#51 loop). Register **two sample git repos/orgs + one sample Obsidian vault** as distinct silos; ingest each; verify:
  - an identically-named entity stays **two nodes** across silos (use **freshly-ingested** silos, not the backfilled blend — §5.1);
  - `GET /graph`/viz **filter per silo and per kind**;
  - a deliberate **cross-silo merge via corrections** applies and reverses;
  - an **`agent_report` silo** (override a vault's kind via `config_json`, or ingest an agent-report source) → its docs **do not** emit co-occurrence edges, and its nodes read back with `kind=agent_report`;
  - `get_entity` / MCP `search_knowledge_graph` return silo + kind.
- [ ] **Step 3: Docs** — note the silo model + provenance kinds + backfill in `docs/graph-corrections.md` (cross-silo proposals are now a source of merge proposals) and wherever ingestion is documented (the featurizer flow-default table).
- [ ] **Step 4: PR + close #50 and #79.** Push; open the PR (do NOT merge without human go-ahead). If the diff is too large for comfortable review, split at the Part A / Part B seam into two stacked PRs — otherwise one PR closing both.

---

## Definition of done
- All five auto-merge paths + the two leaks are silo-scoped, each with a passing test; a test that only checked the faiss query would NOT be sufficient (spec §8).
- Cross-silo similars produce `graph_issues` proposals (by id), not merges; approve+rollback round-trips.
- `documents.silo_id` + `documents.provenance_kind` materialized, indexed/backfilled; `test_schema_mirror` green (both db.py identical).
- Null-silo (loose upload) normalization behaviour unchanged (regression test).
- `provenance_kind` set at ingest from the flow default, overridable via `config_json`; `agent_report` silos suppress co-occurrence emission (incl. the non-`document_collections` vault path).
- `GET /graph`/viz filter per silo **and** per kind; `get_entity`/search/neighborhood/subgraph/document reads surface silo + kind.
- Live acceptance walked on two git repos + a vault, covering distinctness, filtering, cross-silo merge round-trip, agent_report emission gating, and read exposure; **#50 and #79 both closeable.**
