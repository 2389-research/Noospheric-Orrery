# Per-Source Silos + Provenance — Unified Implementation Plan (#50 + #79)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each document a **silo** (its source's stable id) and a **provenance `kind`** (its epistemic nature), both set by the ingestion flow at the same moment. Normalization respects the silo — auto-merge only *within* a silo, never *across* (cross-silo near-duplicates route to the human-gated corrections flow). The `kind` gates co-occurrence emission for opinion sources and is surfaced in every agent read, so a consuming agent can tell "what the code does" from "what an agent thinks." Delivers **#50 and #79 together** — they are one feature (the ingestion flow determines both), built scoping-first then exposure.

**Architecture:** *Materialize the immutable, resolve the mutable.* A materialized `documents.silo_id` (precedence `source_id > collection_id > NULL`, never changes after ingest) — populated at ingest and backfilled. Provenance `kind` (mutable — a user can re-classify a source later) lives as **`provenance_kind` on the silo row** (`watched_sources` + `collections`), stamped with the featurizer's flow default at source registration and editable to override; a `silo_kind` view unifies the two tables so reads/emission resolve kind by joining `documents.silo_id → silo_kind.kind` (one edit propagates everywhere, no staleness). **Five** entity auto-merge paths plus two internal leaks (global `merge_map`, plural collapse) become silo-aware by joining candidates through `entity_sources → documents.silo_id`. Cross-silo near-duplicates are *proposed* to `graph_issues` (by entity id), not merged. `recompute_cooccurrence` (both `db.py`) additionally suppresses edges from gated `kind`s (via the `silo_kind` join). Silo + kind ride along in `GET /graph`, entity reads, the MCP read tools, and a viz filter.

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
- **`kind` lives on the silo row, NOT materialized on `documents` (unlike `silo_id`).** `silo_id` is immutable after ingest → materialize it on `documents`. `kind` is **mutable** — a user can re-classify a source later — so materializing it per-doc creates a staleness bug (a changed override wouldn't propagate to existing docs' reads or emission gate). Instead the **source of truth is `provenance_kind` on the silo row** (`watched_sources` + `collections`), and reads/emission resolve it by joining `documents.silo_id → silo_kind` (the unifying view). One edit to the source row propagates immediately, everywhere. This satisfies LOCKED §10.2 (kind on the silo row). **Do NOT overload `collections.kind`** (which already means the collection *type*: `git_repo`/`tracker_run`) — add a distinct `provenance_kind` column and derive its default from the type via the flow-default map. *(This supersedes the §4.1 "override in `config_json`" wording: the override is now a first-class `provenance_kind` column, which is cleaner and directly editable; `config_json` keeps carrying #41's `ext`/`ignore`/`folder_domains`.)*
- **Stamp-at-registration, edit-to-override (the HuggingFace-pipeline model).** The flow default is applied ONCE, written into `provenance_kind` at source registration/ingest — so a user who does nothing gets the right kind for free. Overriding is editing that one column. Backfill stamps existing silo rows (one row per source, not per doc). A later change to the flow-default *map* does not retro-change already-stamped sources (correct: a source's declared provenance shouldn't silently shift); the user can always edit.
- **Only one kind is gated by default.** Per spec §4 the emission table reduces to: `neutral_summary` leaf emits (rollup already suppressed by the existing membership gate), `human_vault` emits, `human_reviewed` emits, **`agent_report` suppressed.** So the kind-level emission rule is a single predicate `provenance_kind != 'agent_report'`, AND-combined with the existing membership gate. Keep it expressed so it generalizes to a kind→emits map later.

## File-structure map

**Modify (schema/ingest):** `orchestrator/src/db.py`, `worker/src/db.py` (`documents.silo_id` column + index; `provenance_kind` column on `watched_sources` + `collections`; the `silo_kind` view; migrations; backfills — all mirrored) · `worker/src/jobs/upsert_document.py` (populate `silo_id` on doc create/update; stamp source/collection `provenance_kind` default at silo creation) · `orchestrator/src/routes/ingest.py` + the source/repo/tracker registration paths (stamp `provenance_kind` default; accept an optional `kind=` override).
**Create:** `orchestrator/src/pipeline/silo.py` + `worker/src/silo.py` — a tiny shared helper: `resolve_silo_id(source_id, collection_id)`, `flow_default_kind(source_type)`, `resolve_kind(flow_default, override)`, and the SQL fragment "entity has a source in silo S". (Two copies, **mirror-tested** — add `test_silo_is_mirrored` alongside the existing `test_classifier_is_mirrored`.)
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
In `upsert_document` INSERT and UPDATE, set `silo_id = resolve_silo_id(source_id, collection_id)`. For the loose-upload path, `_ingest_document` writes via `store.documents.create(...)` (not a raw INSERT) — so add `silo_id` to `DocumentRepository.create` (interfaces + sqlite_store), passing `None` for loose uploads. (Functionally a no-op for loose uploads since it resolves to NULL, but the file map must name the repository method, not "raw INSERT.")

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
- [ ] **Step 3: Implement.** Add an optional `silo` param to `EntityRepository.get_by_name` and `NormalizationRepository.get_merge_map_entry` (interfaces + sqlite_store). When `silo` is passed, AND the existing query with the `silo_match` EXISTS clause (positional `?`, NULL-safe); back-compat (no silo) when omitted. **Preserve `include_invalid=True`** (the production callers pass it — CLAUDE.md dedup invariant: re-attach to invalidated nodes, don't resurrect duplicates); the silo-aware overload must keep threading it. Thread `silo` through `normalize_entity(store_or_conn, name, entity_type, silo=None)` ← `_ingest_document` (loose upload → `None`). Scope BOTH the merge_map short-circuit and `get_by_name`.
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
   - **disjoint (or null-vs-non-null)** → do NOT merge; insert a pending `graph_issues` row. The worker **cannot import the orchestrator's `pipeline/graph_repair.py`** (`propose_correction`/`apply_merge`/`rollback_merge`), so it does its own insert matching the `graph_issues` DDL: `action='merge'`, `target_entity_id`+`target_entity_name`, `target_b_entity_id`+`target_b_name`, rationale=similarity, keyed on **ids**. ⚠️ **Name collision:** there is a *different* `worker/src/jobs/graph_repair.py` (the advisory judge) — do NOT bolt this insert onto it or confuse it with the orchestrator's correction engine. Any cross-silo pair → `graph_issues`, never `normalization_review_queue`.
   - **Plural collapse** (the pre-faiss stage) — restrict its global `all_names`/`get_by_name` fuse to same-silo names too. For a **multi-silo** entity the singular-lookup is scoped by the entity's full silo-set (same per-silo-set membership test as the pairwise branch), not one arbitrary silo.
- [ ] **Step 3b: Add `"graph_issues"` to `_MIRRORED_TABLES`** (`test_schema_mirror.py`) — Task 6 makes the **worker** a writer of `graph_issues` (Finding 4). Confirm both `db.py` `graph_issues` DDLs are identical.
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(silo): silo-aware worker faiss normalization; propose cross-silo to graph_issues (#50)`.

---

### Task 7: Silo-scope the orchestrator O(n²) batch normalizer — via the STORE path + propose cross-silo

**Files:** Modify `orchestrator/src/repositories/sqlite_store.py::get_all_for_normalization` (silo-aware), `orchestrator/src/pipeline/embedding_normalizer.py::_run_batch_store`. Test: `orchestrator/tests/test_silo_scope_batch_nested.py` — **against the store path** (`test_store` fixture).

- [ ] Same behaviour as Task 6 for this **different** (nested-loop, no faiss) algorithm, but through the repository: `get_all_for_normalization` returns each entity with its silo-set (or the all-pairs loop joins to it); plural collapse + all-pairs comparison auto-merge only same-silo; cross-silo similars → `graph_issues` proposal by id — **reuse `pipeline/graph_repair.propose_correction` here** (the orchestrator CAN import it). The plural-collapse singular lookup (`_run_batch_store` calls `get_by_name(singular, e.type, include_invalid=True)`) must be scoped by the entity's full **silo-set** for multi-silo entities (same rule as Task 6), and **keep `include_invalid=True`** through the silo-aware overload. **Do not regress:** `get_all_for_normalization` currently doesn't filter `invalid_at` — preserve that while adding the silo join. Commit — `feat(silo): silo-aware orchestrator batch normalization via store path (#50)`.

---

### Task 8: Cross-silo merge via corrections round-trips (reuse, verify)

**Files:** Test only — `orchestrator/tests/test_cross_silo_merge_roundtrip.py`. (No new correction code — reuse `graph_repair.apply_merge` / `rollback_merge`.)

- [ ] **Step 1: Test.** Given a proposed cross-silo merge in `graph_issues`, approving it (`resolve_correction`/`apply_merge`) merges the two entities (survivor now has sources in both silos); `rollback_merge` reverses it cleanly (both distinct again, edges restored). Assert the survivor's post-merge multi-silo membership is what the scoping queries (Task 6/7) then see (multi-silo rule).
- [ ] **Step 2–3: Run → pass** (should pass against existing corrections code; if not, the gap is a real finding — surface it). **Commit.**

---

## PART B — Provenance `kind` (#79): tag, gate emission, expose

### Task 9: Provenance `kind` on the silo row — flow default (stamped at registration) + override + `silo_kind` view + backfill

**Files:** Modify `orchestrator/src/db.py`, `worker/src/db.py` (add `provenance_kind` to `watched_sources` + `collections`; the `silo_kind` view; migrations; backfills; mirror). Extend `orchestrator/src/pipeline/silo.py` + `worker/src/silo.py` (`flow_default_kind` + `resolve_kind`). Modify the source-registration + ingest paths that create `watched_sources`/`collections` rows (stamp the default; accept an optional `kind=` override). Test: `orchestrator/tests/test_provenance_kind.py`, `worker/tests/test_kind_populate.py`.

- [ ] **Step 1: Failing tests.**
  - `resolve_kind`: `resolve_kind("neutral_summary", None) == "neutral_summary"`; override wins: `resolve_kind("neutral_summary", "agent_report") == "agent_report"`; unknown override ignored → falls back to default (assert this, so a typo can't silently poison a silo).
  - Schema: `watched_sources` and `collections` both have `provenance_kind`; the `silo_kind` view exists and returns `(silo_id, kind)` for every source/collection.
  - Stamp-at-registration: registering a vault source stamps `watched_sources.provenance_kind = 'human_vault'`; a repo/tracker ingest stamps `collections.provenance_kind = 'neutral_summary'`; passing `kind='agent_report'` at registration stamps that instead.
  - Resolution via the view: for a doc with `silo_id` pointing at a `human_vault` source, `SELECT kind FROM silo_kind WHERE silo_id = ?` → `human_vault`; **after UPDATE-ing that source's `provenance_kind` to `agent_report`, the same query returns `agent_report` with NO doc-level change** (proves no staleness — the fix for review B2).
  - Loose upload (`silo_id IS NULL`) → no `silo_kind` row → resolves to `NULL` (chosen default: "unsourced", treated as non-agent → emits, displayed as unknown).
  - Backfill: existing collections (`kind='git_repo'`/`'tracker_run'`) → `provenance_kind='neutral_summary'`; existing vault `watched_sources` (`type='vault'`) → `human_vault`; existing repo sources → `neutral_summary`.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement.**
  - **Vocabulary + flow-default map in `silo.py` (both copies):**
    ```python
    KINDS = {"neutral_summary", "human_vault", "agent_report", "human_reviewed"}

    # Flow default keyed by featurizer / source type (spec §4.1 point 1).
    FLOW_DEFAULT_KIND = {
        "vault": "human_vault",
        "repo": "neutral_summary", "git_repo": "neutral_summary",
        "tracker": "neutral_summary", "tracker_run": "neutral_summary",
        "codesum": "neutral_summary", "tracksum": "neutral_summary",
    }

    def flow_default_kind(source_type):        # the "pipeline expectation"
        return FLOW_DEFAULT_KIND.get(source_type)  # None if unknown flow

    def resolve_kind(flow_default, override=None):
        """override (a first-class provenance_kind value) wins IF valid; else the flow default."""
        return override if override in KINDS else flow_default
    ```
  - **Schema (both db.py, mirrored; idempotent ALTERs like Task 1):** add `provenance_kind TEXT` to `watched_sources` and to `collections` (distinct from `collections.kind`, which stays the collection *type*). Add the unifying view:
    ```sql
    CREATE VIEW IF NOT EXISTS silo_kind AS
        SELECT id AS silo_id, provenance_kind AS kind FROM watched_sources
        UNION ALL
        SELECT id AS silo_id, provenance_kind AS kind FROM collections;
    ```
    (`documents.silo_id` equals a `watched_sources.id` OR a `collections.id` by the §5 precedence, so a doc matches exactly one `silo_kind` row; null-silo docs match none.) **Invariant the UNION relies on:** both `watched_sources.id` and `collections.id` are `str(uuid.uuid4())` (verified: `routes/watched_sources.py`, `sync_repo.py`, the collection-create path), so a cross-table id collision is astronomically improbable and every doc matches ≤1 view row. State this in the code near the view so a future natural-key change to either table can't silently make the UNION ambiguous. (A watched repo has both a `watched_sources` and a `collections` row; its docs take `silo_id = source_id` by precedence, so they match only the source row — the collection row is a harmless unreferenced entry in the view.) **Schema-mirror the view with a dedicated `test_silo_kind_view_is_mirrored`** whose regex matches `CREATE VIEW IF NOT EXISTS silo_kind AS (.*?);` — do NOT add `silo_kind` to `_MIRRORED_TABLES`/the table list, whose `_table_ddl` regex only matches `CREATE TABLE …` and would fail on a view (reviewer N1).
  - **Stamp at registration:** where each flow creates its silo row — vault/repo source registration → `watched_sources` (`routes/watched_sources.py::create_watched_source`, the registration insert); `POST /ingest/repo` + tracker ingest → `collections` — set `provenance_kind = resolve_kind(flow_default_kind(source_type), override)`. The optional `kind=` override arrives from source registration (a form field, later persisted to the column) or the one-shot ingest call. **No `documents.provenance_kind` column** — kind is never materialized per-doc.
  - **Migration ordering (reviewer N3):** in `init_db`, run `ADD COLUMN provenance_kind` on both tables **before** `CREATE VIEW silo_kind` and **before** `backfill_provenance_kind` — SQLite tolerates a view referencing a not-yet-existent column at CREATE time, but the backfill/first read would fail. On a fresh DB the CREATE TABLEs already carry the column, so ordering is a no-op there.
  - **Backfill** `backfill_provenance_kind(conn)` (both db.py, mirror-tested), called in `init_db` after the ALTERs + view: fill NULL `watched_sources.provenance_kind` from `flow_default_kind(type)`; fill NULL `collections.provenance_kind` from `flow_default_kind(kind)` (the type). One row per source, idempotent. **Existing docs need no change** — they resolve through the view.
- [ ] **Step 4: Run → pass; `test_schema_mirror` green.** Commit — `feat(provenance): provenance_kind on silo rows + silo_kind view + backfill (#79)`.

---

### Task 10: Gate co-occurrence emission by `kind` (`recompute_cooccurrence`, both db.py)

**Files:** Modify `recompute_cooccurrence` in BOTH `orchestrator/src/db.py` and `worker/src/db.py` (mirrored). Test: `orchestrator/tests/test_kind_emission.py`.

- [ ] **Step 1: Failing test.** Two docs in an `agent_report` silo that co-mention entities A,B → after `recompute_cooccurrence`, **no A–B edge** (or its weight excludes the agent_report contribution). The same two docs as a `human_vault` (or `neutral_summary` leaf) silo → the A–B edge **is** present. Critically exercise the **non-`document_collections` path** (a watched *vault* silo with no membership row — spec B6), since that's the case the old `document_collections.emits_cooccurrence` lever could not reach.
- [ ] **Step 2: Run → fail** (today agent_report docs emit edges).
- [ ] **Step 3: Implement.** Resolve each doc's kind via a **correlated scalar subquery on the `silo_kind` view** (NOT a `LEFT JOIN` — reviewer N2: the co-occurrence query's aliases are `d1`/`d2`, there is no `documents` alias to join against, and a subquery avoids any row-multiplication/weight-inflation risk a join could carry). Add the kind predicate **AND-combined** with the existing membership gate so both suppressors work independently (spec §4). Because the co-occurrence join is on `s1.chunk_id = s2.chunk_id` (same chunk ⇒ same document, `d1.id == d2.id`), **one** kind check on that document suffices:
  - existing gate: a doc emits iff `COALESCE(MIN(document_collections.emits_cooccurrence), 1) = 1` (rollup docs suppressed).
  - new gate: `AND COALESCE((SELECT kind FROM silo_kind WHERE silo_id = d1.silo_id), '') != 'agent_report'` (a null-silo/unknown doc has no `silo_kind` row → `COALESCE` → emits).
  Because kind is read live through the view, an override change propagates on the next `recompute_cooccurrence` with no per-doc backfill. Express the predicate so it generalizes to a kind→emits map later (a `CASE`/lookup) rather than hard-coding one string if it recurs. Mirror the change in both `db.py`; the subquery sits exactly alongside the existing `document_collections` `MIN(emits_cooccurrence)` subquery.
- [ ] **Step 4: Run → pass; `test_schema_mirror` green (both `recompute_cooccurrence` identical).** Commit — `feat(provenance): gate co-occurrence emission for agent_report silos (#79)`.

---

### Task 11: Expose silo + kind in reads, MCP, and viz (closes #50's "filterable" + #79's exposure)

**Files:** Modify `orchestrator/src/pipeline/graph_v5.py` (+ snapshot builder), entity read routes, `orchestrator/src/mcp_server.py` (annotate nodes/sources), `orchestrator/src/routes/graph.py` (`?silo=`/`?kind=` post-filter), `frontend/public/viz/*` (filter control). Test: `orchestrator/tests/test_graph_silo_filter.py`, `orchestrator/tests/test_reads_expose_provenance.py`.

- [ ] **Step 1: Failing tests.**
  - `GET /graph` nodes carry `silo_id` **and** `provenance_kind`; `?silo=<id>` returns only that silo's nodes/edges (`?silo=none` for the null pool); `?kind=<k>` filters by kind.
  - `get_entity` sources annotate silo + kind; `search_knowledge_graph` / `get_neighborhood` / `get_subgraph` (MCP, the #48 read path) include silo + kind on nodes; document reads include the doc's silo + kind.
- [ ] **Step 2–4: Implement (mind the cached snapshot — Finding 7).** `GET /graph` serves a **materialized snapshot** via `get_or_build` (`routes/graph.py`, `graph_snapshot.py`), not a live query. So: (a) in the **snapshot builder** `graph_v5.build_graph_v5(store, …)`, attach each node's `silo_id` (from `documents`) and resolve its `kind` via the `silo_kind` view join (kind is NOT a doc column). *Note the snapshot is cached — a later kind override won't appear until the snapshot rebuilds; that's acceptable for the viz (the emission gate and live entity/MCP reads pick it up immediately), but if fresher viz kind matters, invalidate the snapshot on source-config change.* (b) apply `?silo=`/`?kind=` as a **post-filter over the loaded payload** in the route (snapshot stays whole/cached). For `get_entity`/`get_document`/`search`/`neighborhood`/`subgraph`, resolve silo + kind through the `silo_kind` join at read time (live, no staleness). Add a viz filter control (silo + kind) — **verify per CLAUDE.md canvas rules: drive a browser + screenshot + model-judge; Canvas2D can't be DOM-inspected;** use `window.__viz` hooks in the galaxy view.
- [ ] **Step 5: Commit** — `feat(provenance): expose silo + kind in graph/entity/MCP reads + viz filter (#50, #79)`.

---

## PART C — Verify & ship

### Task 12: Full suite, live acceptance (both issues), docs, close #50 + #79

- [ ] **Step 1:** Run the full orchestrator suite (native/CI) and the full worker suite (container, `uv run`) — all green (minus the documented pre-existing deselects). `test_schema_mirror` green.
- [ ] **Step 2: Live acceptance** (rebuild stack; the #41/#51 loop). Register **two sample git repos/orgs + one sample Obsidian vault** as distinct silos; ingest each; verify:
  - an identically-named entity stays **two nodes** across silos (use **freshly-ingested** silos, not the backfilled blend — §5.1);
  - `GET /graph`/viz **filter per silo and per kind**;
  - a deliberate **cross-silo merge via corrections** applies and reverses;
  - an **`agent_report` silo** (edit a source's `provenance_kind` to `agent_report`, or ingest an agent-report source) → its docs **do not** emit co-occurrence edges, and its nodes read back with `kind=agent_report`;
  - **override propagation (the B2 fix):** flip a live source's `provenance_kind`, re-run `recompute_cooccurrence` → emission changes accordingly with NO re-ingest; `get_entity` reflects the new kind immediately;
  - `get_entity` / MCP `search_knowledge_graph` return silo + kind.
- [ ] **Step 3: Docs** — note the silo model + provenance kinds + backfill in `docs/graph-corrections.md` (cross-silo proposals are now a source of merge proposals) and wherever ingestion is documented (the featurizer flow-default table).
- [ ] **Step 4: PR + close #50 and #79.** Push; open the PR (do NOT merge without human go-ahead). If the diff is too large for comfortable review, split at the Part A / Part B seam into two stacked PRs — otherwise one PR closing both.

---

## Definition of done
- All five auto-merge paths + the two leaks are silo-scoped, each with a passing test; a test that only checked the faiss query would NOT be sufficient (spec §8).
- Cross-silo similars produce `graph_issues` proposals (by id), not merges; approve+rollback round-trips.
- `documents.silo_id` materialized/indexed/backfilled; `provenance_kind` on the silo rows (`watched_sources` + `collections`) with the `silo_kind` view; `test_schema_mirror` green (both db.py identical, view + new columns mirror-covered).
- Null-silo (loose upload) normalization behaviour unchanged (regression test).
- `provenance_kind` stamped at registration from the flow default, overridable by editing the source's column; changing it **propagates live** (emission + reads) with no re-ingest (B2 fixed); `agent_report` silos suppress co-occurrence emission (incl. the non-`document_collections` vault path).
- `GET /graph`/viz filter per silo **and** per kind; `get_entity`/search/neighborhood/subgraph/document reads surface silo + kind.
- Live acceptance walked on two git repos + a vault, covering distinctness, filtering, cross-silo merge round-trip, agent_report emission gating, and read exposure; **#50 and #79 both closeable.**
