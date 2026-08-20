# Domain Charter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a domain expert declare their canonical domain, its aliases, and their extraction spec in one charter, so their opinion governs extraction from document one instead of waiting 20 documents for a simmer job.

**Architecture:** A charter writes into three slots that already exist — a `domains` row, `domain_merge_map` rows, and a `specs` row marked `source='authored'`. A new `specs.source` column carries the *contract*: authored specs are complete and suppress the general extraction pass; simmered specs are additive and require it. A pure `resolve_extraction_plan()` function decides which specs run and whether the general pass runs, and `ingest.py` consumes it.

**Tech Stack:** Python 3.12, FastAPI, SQLite (WAL), pytest + pytest-asyncio, Pydantic v2.

**Spec:** `docs/superpowers/specs/2026-08-20-domain-charter-design.md`

## Global Constraints

- **The no-opinion guarantee:** with no charter present, ingest behaviour must be byte-identical to today. Existing tests in `orchestrator/tests/test_ingest_route.py` must pass **unmodified** at every task boundary. If a task requires editing them, the task is wrong.
- **Schema changes land in BOTH `orchestrator/src/db.py` and `worker/src/db.py`.** The two processes open the same database files; whichever opens a workspace first decides its shape.
- **Do NOT add `specs` to `_MIRRORED_TABLES`** in `orchestrator/tests/test_schema_mirror.py`. The two `specs` DDL blocks already differ in column order (`media_type` before `created_at` in the orchestrator, after it in the worker). That divergence predates this work and is harmless for `ALTER TABLE`-added columns; adding the table to the mirror list would fail on formatting rather than catch drift.
- **Never edit `classifier.py`.** This plan does not touch it. `orchestrator/src/pipeline/classifier.py` and `worker/src/classifier.py` are enforced byte-identical below their ABOUTME headers.
- **Charter aliases are stored `.lower().strip()`.** Both lookup paths (`domain_normalizer.py:22`, `sqlite_store.py:278`) normalise the key that way; an alias stored in any other form silently never matches.
- **Use `get_connection()` from `db.py`** for any new SQLite access. Never open SQLite directly, never re-specify the WAL/busy_timeout PRAGMAs.
- **Default `source` is `'simmered'`** so every existing spec row keeps today's behaviour.
- ABOUTME headers: new Python files start with two `# ABOUTME:` comment lines, matching the codebase convention.

---

### Task 1: `specs.source` column

Adds the column that carries the authored/simmered contract, in both schemas, plus the dataclass and repository plumbing. Nothing reads it yet.

**Files:**
- Modify: `orchestrator/src/db.py` (SCHEMA `specs` block ~line 195; migration block ~line 309)
- Modify: `worker/src/db.py` (SCHEMA `specs` block ~line 173; migration block ~line 279)
- Modify: `orchestrator/src/repositories/interfaces.py:97-104` (`Spec` dataclass), `:346-347` (`SpecRepository.create`)
- Modify: `orchestrator/src/repositories/sqlite_store.py:655-681` (`SQLiteSpecRepository`)
- Test: `orchestrator/tests/test_spec_source.py` (create)

**Interfaces:**
- Consumes: nothing
- Produces: `Spec.source: str` (`'authored'` | `'simmered'`, default `'simmered'`); `SpecRepository.create(id, domain_path, version, content, golden_set=None, score=None, source='simmered')`

- [ ] **Step 1: Write the failing test**

Create `orchestrator/tests/test_spec_source.py`:

```python
# ABOUTME: specs.source carries the authored/simmered contract, not just provenance.
# ABOUTME: Authored specs are complete; simmered ones are additive. Defaults must not shift.

import os
import pytest

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db, get_connection
from src.repositories.sqlite_store import SQLiteDataStore


def test_spec_defaults_to_simmered(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    store.specs.create("s1", "legal/contracts", 1, "content")
    spec = store.specs.get_for_domain("legal/contracts")
    assert spec.source == "simmered"
    store.close()


def test_spec_can_be_authored(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    store.specs.create("s1", "legal/contracts", 1, "content", source="authored")
    spec = store.specs.get_for_domain("legal/contracts")
    assert spec.source == "authored"
    store.close()


def test_general_spec_carries_source(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    store.specs.create("s1", None, 1, "general content")
    assert store.specs.get_general().source == "simmered"
    store.close()


def test_migration_backfills_existing_rows(tmp_path):
    """A database created before this column must gain it with the safe default."""
    db_path = str(tmp_path / "legacy.db")
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE specs (
            id TEXT PRIMARY KEY, domain_path TEXT, version INTEGER,
            spec_content TEXT, golden_set TEXT, score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.execute("INSERT INTO specs (id, domain_path, version, spec_content) VALUES ('old', 'a/b', 1, 'x')")
    conn.commit()
    conn.close()

    init_db(db_path)

    store = SQLiteDataStore(db_path)
    assert store.specs.get_for_domain("a/b").source == "simmered"
    store.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd orchestrator && pytest tests/test_spec_source.py -v`
Expected: FAIL — `TypeError: create() got an unexpected keyword argument 'source'` and `AttributeError: 'Spec' object has no attribute 'source'`

- [ ] **Step 3: Add the column to both schemas**

In `orchestrator/src/db.py`, the `specs` CREATE TABLE becomes:

```sql
CREATE TABLE IF NOT EXISTS specs (
    id TEXT PRIMARY KEY,
    domain_path TEXT,
    version INTEGER,
    spec_content TEXT,
    golden_set TEXT,
    score REAL,
    media_type TEXT DEFAULT 'text',
    source TEXT DEFAULT 'simmered',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

In `worker/src/db.py`, the `specs` CREATE TABLE becomes:

```sql
CREATE TABLE IF NOT EXISTS specs (
    id TEXT PRIMARY KEY,
    domain_path TEXT,
    version INTEGER,
    spec_content TEXT,
    golden_set TEXT,
    score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    media_type TEXT DEFAULT 'text',
    source TEXT DEFAULT 'simmered'
);
```

(The column order difference is pre-existing — preserve each file's own order and just append `source`.)

- [ ] **Step 4: Add the migration to both files**

In `orchestrator/src/db.py`, immediately after the existing `media_type` migration:

```python
            # Migrate specs table
            spec_cols = {r[1] for r in conn.execute("PRAGMA table_info(specs)").fetchall()}
            if "media_type" not in spec_cols:
                conn.execute("ALTER TABLE specs ADD COLUMN media_type TEXT DEFAULT 'text'")
            # `source` is the authored/simmered CONTRACT, not just provenance: an authored
            # spec is complete and suppresses the general pass, a simmered one is additive
            # and depends on it. Existing rows are all simmered.
            if "source" not in spec_cols:
                conn.execute("ALTER TABLE specs ADD COLUMN source TEXT DEFAULT 'simmered'")
```

In `worker/src/db.py`, the same two lines after its `media_type` migration (note: no leading indentation beyond the existing block's).

- [ ] **Step 5: Update the dataclass and the abstract signature**

In `orchestrator/src/repositories/interfaces.py`, the `Spec` dataclass:

```python
@dataclass
class Spec:
    id: str
    domain_path: str | None
    version: int
    spec_content: str
    golden_set: str | None = None
    score: float | None = None
    created_at: str | None = None
    source: str = "simmered"
```

And `SpecRepository.create`:

```python
    @abstractmethod
    def create(self, id: str, domain_path: str | None, version: int,
               content: str, golden_set: str | None = None, score: float | None = None,
               source: str = "simmered") -> None: ...
```

- [ ] **Step 6: Update the SQLite implementation**

In `orchestrator/src/repositories/sqlite_store.py`, `SQLiteSpecRepository`:

```python
    def create(self, id, domain_path, version, content, golden_set=None, score=None,
               source="simmered"):
        self._conn.execute(
            "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, domain_path, version, content, golden_set, score, source),
        )
        self._conn.commit()

    def get_general(self):
        row = self._conn.execute(
            "SELECT * FROM specs WHERE domain_path IS NULL ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return Spec(id=row["id"], domain_path=None, version=row["version"],
                    spec_content=row["spec_content"], golden_set=row["golden_set"],
                    score=row["score"], source=row["source"] or "simmered")

    def get_for_domain(self, domain_path):
        row = self._conn.execute(
            "SELECT * FROM specs WHERE domain_path = ? ORDER BY version DESC LIMIT 1",
            (domain_path,),
        ).fetchone()
        if not row:
            return None
        return Spec(id=row["id"], domain_path=row["domain_path"], version=row["version"],
                    spec_content=row["spec_content"], golden_set=row["golden_set"],
                    score=row["score"], source=row["source"] or "simmered")
```

`row["source"] or "simmered"` guards the migrated-NULL case: `ALTER TABLE ... DEFAULT` applies to new rows, and existing rows read back NULL.

- [ ] **Step 7: Run the new tests**

Run: `cd orchestrator && pytest tests/test_spec_source.py -v`
Expected: PASS (4 tests)

- [ ] **Step 8: Run the full suites to confirm nothing regressed**

Run: `cd orchestrator && pytest tests/ -q && cd ../worker && pytest tests/ -q`
Expected: PASS, including `test_schema_mirror.py`

- [ ] **Step 9: Commit**

```bash
git add orchestrator/src/db.py worker/src/db.py \
        orchestrator/src/repositories/interfaces.py \
        orchestrator/src/repositories/sqlite_store.py \
        orchestrator/tests/test_spec_source.py
git commit -m "feat(specs): add source column carrying the authored/simmered contract"
```

---

### Task 2: `resolve_extraction_plan`

The pure decision function, with no ingest wiring. Extracting it from `ingest.py` first makes it independently testable — the current ancestor walk is buried mid-function and has no tests of its own.

**Files:**
- Create: `orchestrator/src/pipeline/extraction_plan.py`
- Test: `orchestrator/tests/test_extraction_plan.py` (create)

**Interfaces:**
- Consumes: `Spec.source` from Task 1
- Produces: `resolve_extraction_plan(store, domains: list[str]) -> tuple[bool, list[Spec]]` returning `(run_general, specs)`

- [ ] **Step 1: Write the failing test**

Create `orchestrator/tests/test_extraction_plan.py`:

```python
# ABOUTME: resolve_extraction_plan decides which domain specs run and whether the
# ABOUTME: general pass runs. An authored spec is complete, so it suppresses general.

import os
import pytest

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db
from src.repositories.sqlite_store import SQLiteDataStore
from src.pipeline.extraction_plan import resolve_extraction_plan


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    s = SQLiteDataStore(db_path)
    yield s
    s.close()


def test_no_specs_runs_general_only(store):
    run_general, specs = resolve_extraction_plan(store, ["legal/contracts"])
    assert run_general is True
    assert specs == []


def test_simmered_spec_still_runs_general(store):
    store.specs.create("s1", "legal/contracts", 1, "domain content", source="simmered")
    run_general, specs = resolve_extraction_plan(store, ["legal/contracts"])
    assert run_general is True
    assert [s.id for s in specs] == ["s1"]


def test_authored_spec_suppresses_general(store):
    store.specs.create("s1", "legal/contracts", 1, "domain content", source="authored")
    run_general, specs = resolve_extraction_plan(store, ["legal/contracts"])
    assert run_general is False
    assert [s.id for s in specs] == ["s1"]


def test_authored_spec_at_ancestor_applies_and_suppresses(store):
    store.specs.create("s1", "legal", 1, "ancestor content", source="authored")
    run_general, specs = resolve_extraction_plan(store, ["legal/contracts/nda"])
    assert run_general is False
    assert [s.id for s in specs] == ["s1"]


def test_authored_primary_with_simmered_secondary(store):
    """The authored spec suppresses the GENERAL pass, not other domain specs."""
    store.specs.create("s1", "legal/contracts", 1, "authored", source="authored")
    store.specs.create("s2", "business/finance", 1, "simmered", source="simmered")
    run_general, specs = resolve_extraction_plan(
        store, ["legal/contracts", "business/finance"])
    assert run_general is False
    assert {s.id for s in specs} == {"s1", "s2"}


def test_specs_are_deepest_first(store):
    store.specs.create("s_shallow", "legal", 1, "shallow", source="simmered")
    store.specs.create("s_deep", "legal/contracts", 1, "deep", source="simmered")
    _, specs = resolve_extraction_plan(store, ["legal/contracts"])
    assert [s.id for s in specs] == ["s_deep", "s_shallow"]


def test_a_spec_shared_by_two_domains_is_not_run_twice(store):
    store.specs.create("s1", "legal", 1, "shared", source="simmered")
    _, specs = resolve_extraction_plan(store, ["legal/contracts", "legal/ip"])
    assert [s.id for s in specs] == ["s1"]


def test_latest_version_wins(store):
    store.specs.create("s1", "legal/contracts", 1, "v1", source="simmered")
    store.specs.create("s2", "legal/contracts", 2, "v2", source="authored")
    run_general, specs = resolve_extraction_plan(store, ["legal/contracts"])
    assert run_general is False
    assert [s.id for s in specs] == ["s2"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd orchestrator && pytest tests/test_extraction_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pipeline.extraction_plan'`

- [ ] **Step 3: Write the implementation**

Create `orchestrator/src/pipeline/extraction_plan.py`:

```python
# ABOUTME: Decides which extraction passes run for a document's domains.
# ABOUTME: An authored spec is complete and suppresses the general pass; a simmered one is not.

from ..repositories.interfaces import Spec


def resolve_extraction_plan(store, domains: list[str]) -> tuple[bool, list[Spec]]:
    """Resolve the extraction passes for a document assigned to `domains`.

    Returns `(run_general, specs)`.

    Walks each domain's ancestors deepest-first and collects every spec found,
    deduplicated by spec id — a spec shared by two of the document's domains runs once.

    `run_general` is False when any resolved spec is authored. The two spec sources carry
    different CONTRACTS, and the distinction is load-bearing:

      - a SIMMERED domain spec is additive by design (see worker/src/jobs/simmer_domain.py:
        "general spec handles the base types"). Suppressing the general pass alongside one
        would silently drop every base entity type.
      - an AUTHORED spec is a domain expert's complete declaration of what matters. Running
        the general pass alongside it would reintroduce exactly the entities they excluded.

    So the rule is narrow on purpose: general is skipped ONLY when an authored spec applies.
    """
    specs: list[Spec] = []
    seen_specs: set[str] = set()

    for domain_path in domains:
        parts = domain_path.split("/")
        ancestor_paths = ["/".join(parts[:i + 1]) for i in range(len(parts))]
        for ancestor in reversed(ancestor_paths):  # deepest first
            domain_spec = store.specs.get_for_domain(ancestor)
            if domain_spec and domain_spec.id not in seen_specs:
                seen_specs.add(domain_spec.id)
                specs.append(domain_spec)

    run_general = not any(s.source == "authored" for s in specs)
    return run_general, specs
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd orchestrator && pytest tests/test_extraction_plan.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/extraction_plan.py orchestrator/tests/test_extraction_plan.py
git commit -m "feat(pipeline): add resolve_extraction_plan deciding general-pass suppression"
```

---

### Task 3: Wire the plan into ingest

Replaces the inline ancestor walk and makes the general pass conditional. This is the task that must not change behaviour when no charter exists.

**Files:**
- Modify: `orchestrator/src/routes/ingest.py:108-182` (steps 3 and 4 of `_ingest_document`), and the import block at `:14-25`
- Test: `orchestrator/tests/test_ingest_authored_spec.py` (create)

**Interfaces:**
- Consumes: `resolve_extraction_plan(store, domains) -> (run_general, specs)` from Task 2
- Produces: no new public interface

- [ ] **Step 1: Write the failing test**

Create `orchestrator/tests/test_ingest_authored_spec.py`:

```python
# ABOUTME: An authored spec replaces the general extraction pass for its domain.
# ABOUTME: With no authored spec anywhere, ingest must behave exactly as it did before.

import os
import pytest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db
from src.config import Settings
from src.repositories.sqlite_store import SQLiteDataStore
from src.repositories.factory import set_test_store

MOCK_CLASSIFICATION = {
    "primary_domain": "legal/contracts",
    "secondary_domains": [],
    "confidence": 0.9,
}
MOCK_ENTITIES = [{"name": "acme corp", "type": "Party"}]


def make_store(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    set_test_store(store)
    return store


def make_settings(tmp_path):
    return Settings(
        aws_access_key="test-key", aws_secret_key="test-secret",
        db_path=str(tmp_path / "test.db"),
        documents_dir=str(tmp_path / "documents"),
    )


async def _run_ingest(store, tmp_path, extract_mock):
    with patch("src.routes.ingest.get_settings", return_value=make_settings(tmp_path)), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock,
               return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.extract_document", new=extract_mock), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _ingest_document
        return await _ingest_document(store, "NDA", "Acme Corp agrees to...", None)


@pytest.mark.asyncio
async def test_no_authored_spec_runs_general_pass(tmp_path):
    store = make_store(tmp_path)
    extract = AsyncMock(return_value=MOCK_ENTITIES)
    await _run_ingest(store, tmp_path, extract)

    specs_used = [c.kwargs["spec"] for c in extract.await_args_list]
    assert len(specs_used) == 1, "general pass should run exactly once"

    passes = {r["extraction_pass"] for r in
              store.conn.execute("SELECT extraction_pass FROM entity_sources").fetchall()}
    assert passes == {"general"}
    set_test_store(None)
    store.close()


@pytest.mark.asyncio
async def test_authored_spec_replaces_general_pass(tmp_path):
    store = make_store(tmp_path)
    store.domains.create("d1", "legal/contracts", "legal")
    store.specs.create("s1", "legal/contracts", 1, "MY AUTHORED SPEC", source="authored")

    extract = AsyncMock(return_value=MOCK_ENTITIES)
    await _run_ingest(store, tmp_path, extract)

    specs_used = [c.kwargs["spec"] for c in extract.await_args_list]
    assert specs_used == ["MY AUTHORED SPEC"], "only the authored spec should run"

    passes = {r["extraction_pass"] for r in
              store.conn.execute("SELECT extraction_pass FROM entity_sources").fetchall()}
    assert passes == {"domain-specific"}
    set_test_store(None)
    store.close()


@pytest.mark.asyncio
async def test_simmered_spec_runs_alongside_general(tmp_path):
    store = make_store(tmp_path)
    store.domains.create("d1", "legal/contracts", "legal")
    store.specs.create("s1", "legal/contracts", 1, "SIMMERED SPEC", source="simmered")

    extract = AsyncMock(return_value=MOCK_ENTITIES)
    await _run_ingest(store, tmp_path, extract)

    specs_used = [c.kwargs["spec"] for c in extract.await_args_list]
    assert len(specs_used) == 2, "general pass plus the simmered domain spec"
    assert "SIMMERED SPEC" in specs_used
    set_test_store(None)
    store.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd orchestrator && pytest tests/test_ingest_authored_spec.py -v`
Expected: `test_authored_spec_replaces_general_pass` FAILS — two specs are used, because the general pass is currently unconditional.

- [ ] **Step 3: Add the import**

In `orchestrator/src/routes/ingest.py`, after the existing `from ..pipeline.domain_normalizer import assign_document_domains` line:

```python
from ..pipeline.extraction_plan import resolve_extraction_plan
```

- [ ] **Step 4: Replace steps 3 and 4**

Replace everything from `# 3. Extract — use simmered general spec if available...` (`:108`) through the end of the step-4 block (`:182`, ending `store.documents.update_status(doc_id, "enriched")`) with:

```python
    # 3. Extract. An AUTHORED domain spec is a complete declaration by a domain expert,
    # so it replaces the general pass; a SIMMERED one is additive and runs alongside it.
    run_general, domain_specs = resolve_extraction_plan(store, domains)

    entity_count = 0
    chunk_entities: dict[str, list[str]] = {}

    if run_general:
        spec = store.specs.get_general()
        spec_content = spec.spec_content if spec else GENERAL_TEXT_SPEC
        spec_version = spec.version if spec else 0
        extraction_pass = "general_simmered" if spec else "general"

        entities = await extract_document(
            relay=relay, chunks=chunks, spec=spec_content, model=settings.extraction_model,
        )
        for entity in entities:
            entity_id = normalize_entity(store, entity["name"], entity["type"])
            store.entity_sources.create(
                entity_id=entity_id,
                document_id=doc_id,
                chunk_id=entity.get("chunk_id"),
                extraction_pass=extraction_pass,
                spec_version=spec_version,
            )
            chunk_id = entity.get("chunk_id")
            if chunk_id:
                chunk_entities.setdefault(chunk_id, []).append(entity_id)
        entity_count = len(entities)

    store.documents.update_status(doc_id, "extracted")

    # 4. Run the resolved domain specs (deepest first, deduplicated)
    domain_entity_count = 0
    for domain_spec in domain_specs:
        d_entities = await extract_document(
            relay=relay, chunks=chunks,
            spec=domain_spec.spec_content, model=settings.extraction_model,
        )
        for entity in d_entities:
            entity_id = normalize_entity(store, entity["name"], entity["type"])
            store.entity_sources.create(
                entity_id=entity_id,
                document_id=doc_id,
                chunk_id=entity.get("chunk_id"),
                extraction_pass="domain-specific",
                spec_version=domain_spec.version,
            )
            chunk_id = entity.get("chunk_id")
            if chunk_id:
                chunk_entities.setdefault(chunk_id, []).append(entity_id)
        domain_entity_count += len(d_entities)

    # Co-occurrence is computed once over the accumulated chunk->entity map. The previous
    # code recomputed it inside the per-domain loop; the upserts are idempotent and the map
    # only grows, so the final edge set is identical — this just stops redoing the work.
    edges = compute_cooccurrence_edges(chunk_entities)
    for edge in edges:
        store.relationships.upsert_cooccurrence(
            edge["id"], edge["from"], edge["to"], edge["weight"], edge["source_chunk"],
        )

    if domain_entity_count > 0:
        entity_count += domain_entity_count
        store.documents.update_status(doc_id, "enriched")
```

- [ ] **Step 5: Run the new tests**

Run: `cd orchestrator && pytest tests/test_ingest_authored_spec.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Verify the no-opinion guarantee**

Run: `cd orchestrator && pytest tests/test_ingest_route.py -v`
Expected: PASS, with **zero edits** to that file. If it needed changing, revert and rethink Step 4.

- [ ] **Step 7: Run the full suite**

Run: `cd orchestrator && pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add orchestrator/src/routes/ingest.py orchestrator/tests/test_ingest_authored_spec.py
git commit -m "feat(ingest): authored domain specs replace the general extraction pass"
```

---

### Task 4: `dry_run` on `POST /ingest`

The conversation's critique surface: classify and extract a real document, return what would happen, persist nothing.

**Files:**
- Modify: `orchestrator/src/models.py:62-71` (add `DryRunResult`)
- Modify: `orchestrator/src/routes/ingest.py` (add `_dry_run_document`, add the query param to `ingest_file` at `:347`)
- Test: `orchestrator/tests/test_ingest_dry_run.py` (create)

**Interfaces:**
- Consumes: `resolve_extraction_plan` from Task 2
- Produces: `_dry_run_document(store, title: str, content: str) -> dict` with keys `primary_domain: str`, `secondary_domains: list[str]`, `confidence: float`, `run_general: bool`, `specs_applied: list[str]`, `entity_types: list[dict]` where each entry is `{"type": str, "count": int, "examples": list[str]}`

- [ ] **Step 1: Write the failing test**

Create `orchestrator/tests/test_ingest_dry_run.py`:

```python
# ABOUTME: Dry-run classifies and extracts a document and persists absolutely nothing.
# ABOUTME: It is the critique surface the charter conversation is built on.

import os
import pytest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db
from src.config import Settings
from src.repositories.sqlite_store import SQLiteDataStore
from src.repositories.factory import set_test_store

MOCK_CLASSIFICATION = {
    "primary_domain": "legal/contracts",
    "secondary_domains": ["business/finance"],
    "confidence": 0.9,
}
MOCK_ENTITIES = [
    {"name": "acme corp", "type": "Party"},
    {"name": "globex", "type": "Party"},
    {"name": "2026-01-03", "type": "Date"},
]


def make_store(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    set_test_store(store)
    return store


async def _dry_run(store, tmp_path):
    settings = Settings(
        aws_access_key="test-key", aws_secret_key="test-secret",
        db_path=str(tmp_path / "test.db"), documents_dir=str(tmp_path / "documents"),
    )
    with patch("src.routes.ingest.get_settings", return_value=settings), \
         patch("src.routes.ingest.classify_document", new_callable=AsyncMock,
               return_value=MOCK_CLASSIFICATION), \
         patch("src.routes.ingest.extract_document", new_callable=AsyncMock,
               return_value=MOCK_ENTITIES), \
         patch("src.routes.ingest.Relay"):
        from src.routes.ingest import _dry_run_document
        return await _dry_run_document(store, "NDA", "Acme Corp agrees to pay Globex.")


@pytest.mark.asyncio
async def test_dry_run_reports_classification_and_types(tmp_path):
    store = make_store(tmp_path)
    result = await _dry_run(store, tmp_path)

    assert result["primary_domain"] == "legal/contracts"
    assert result["secondary_domains"] == ["business/finance"]
    assert result["run_general"] is True

    by_type = {t["type"]: t for t in result["entity_types"]}
    assert by_type["Party"]["count"] == 2
    assert set(by_type["Party"]["examples"]) == {"acme corp", "globex"}
    assert by_type["Date"]["count"] == 1
    set_test_store(None)
    store.close()


@pytest.mark.asyncio
async def test_dry_run_persists_nothing(tmp_path):
    store = make_store(tmp_path)
    await _dry_run(store, tmp_path)

    for table in ("documents", "chunks", "entities", "entity_sources",
                  "domains", "document_domains"):
        count = store.conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
        assert count == 0, f"dry run wrote {count} row(s) to {table}"
    set_test_store(None)
    store.close()


@pytest.mark.asyncio
async def test_dry_run_reports_authored_spec_suppression(tmp_path):
    store = make_store(tmp_path)
    store.domains.create("d1", "legal/contracts", "legal")
    store.specs.create("s1", "legal/contracts", 1, "AUTHORED", source="authored")

    result = await _dry_run(store, tmp_path)
    assert result["run_general"] is False
    assert result["specs_applied"] == ["legal/contracts"]
    set_test_store(None)
    store.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd orchestrator && pytest tests/test_ingest_dry_run.py -v`
Expected: FAIL — `ImportError: cannot import name '_dry_run_document'`

- [ ] **Step 3: Add the response model**

In `orchestrator/src/models.py`, after `IngestResult`:

```python
class DryRunEntityType(BaseModel):
    type: str
    count: int
    examples: list[str]


class DryRunResult(BaseModel):
    primary_domain: str
    secondary_domains: list[str]
    confidence: float
    run_general: bool
    specs_applied: list[str]
    entity_types: list[DryRunEntityType]
```

- [ ] **Step 4: Implement `_dry_run_document`**

In `orchestrator/src/routes/ingest.py`, add after `_ingest_document`:

```python
async def _dry_run_document(store, title: str, content: str) -> dict:
    """Classify and extract a document WITHOUT writing anything.

    Deliberately avoids `assign_document_domains`/`normalize_domain_label`, which create
    domain rows as a side effect. Merge targets are resolved read-only instead, so a dry
    run over an unfamiliar document cannot pollute the taxonomy the classifier reads.
    """
    settings = get_settings()
    relay = Relay.from_settings(settings)

    chunks = chunk_document(content, chunk_size=settings.chunk_size)
    for i, chunk in enumerate(chunks):
        chunk["id"] = f"dry-run-{i}"

    excerpt = build_classification_excerpt(title, content)
    classification = await classify_document(
        relay=relay, title=title, excerpt=excerpt,
        existing_taxonomy=store.domains.get_all_paths(),
        model=settings.classification_model,
    )

    def _resolve(label: str) -> str:
        return store.domains.get_merge_target(label) or label

    primary = _resolve(classification.get("primary_domain") or "")
    secondaries = [_resolve(s) for s in classification.get("secondary_domains", [])]
    domains = [d for d in [primary, *secondaries] if d]

    run_general, domain_specs = resolve_extraction_plan(store, domains)

    entities: list[dict] = []
    if run_general:
        spec = store.specs.get_general()
        entities += await extract_document(
            relay=relay, chunks=chunks,
            spec=spec.spec_content if spec else GENERAL_TEXT_SPEC,
            model=settings.extraction_model,
        )
    for domain_spec in domain_specs:
        entities += await extract_document(
            relay=relay, chunks=chunks, spec=domain_spec.spec_content,
            model=settings.extraction_model,
        )

    grouped: dict[str, list[str]] = {}
    for entity in entities:
        grouped.setdefault(entity["type"], []).append(entity["name"])

    entity_types = [
        {"type": t, "count": len(names), "examples": list(dict.fromkeys(names))[:3]}
        for t, names in sorted(grouped.items(), key=lambda kv: -len(kv[1]))
    ]

    return {
        "primary_domain": primary,
        "secondary_domains": secondaries,
        "confidence": classification.get("confidence", 0.0),
        "run_general": run_general,
        "specs_applied": [s.domain_path for s in domain_specs],
        "entity_types": entity_types,
    }
```

- [ ] **Step 5: Run the tests**

Run: `cd orchestrator && pytest tests/test_ingest_dry_run.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Expose it on the route**

In `orchestrator/src/routes/ingest.py`, change the `ingest_file` signature at `:347`:

```python
@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_file(
    response: Response,
    file: UploadFile = File(...),
    dry_run: bool = False,
    auth: AuthStore = Depends(get_auth_store),
):
```

`response_model=IngestResult` is removed because the endpoint now returns one of two shapes; both are still validated by the models below. Immediately after `file_bytes = await file.read()` and the size check, add:

```python
    if dry_run:
        text = file_bytes.decode("utf-8", errors="replace")
        result = await _dry_run_document(auth.store, title, text)
        response.status_code = status.HTTP_200_OK
        return DryRunResult(**result)
```

Add `DryRunResult` to the `..models` import at `:15`.

- [ ] **Step 7: Verify existing route tests still pass**

Run: `cd orchestrator && pytest tests/test_ingest_route.py tests/test_rest_hygiene.py -v`
Expected: PASS. If `test_rest_hygiene.py` asserts on the declared response model of `POST /ingest`, prefer keeping `response_model=IngestResult` and returning a plain dict from the `dry_run` branch instead.

- [ ] **Step 8: Commit**

```bash
git add orchestrator/src/models.py orchestrator/src/routes/ingest.py \
        orchestrator/tests/test_ingest_dry_run.py
git commit -m "feat(ingest): add dry_run that classifies and extracts without persisting"
```

---

### Task 5: `POST /charter` and `GET /charter`

The single write endpoint. Four writes, one transaction.

**Files:**
- Create: `orchestrator/src/routes/charter.py`
- Modify: `orchestrator/src/models.py` (add `CharterRequest`)
- Modify: `orchestrator/src/main.py:157-174` (register the router)
- Test: `orchestrator/tests/test_charter_route.py` (create)

**Interfaces:**
- Consumes: `SpecRepository.create(..., source=)` from Task 1
- Produces: `POST /charter` accepting `{domain: str, aliases: list[str], spec: str}` → `{domain, aliases_written: int, spec_version: int}`; `GET /charter?domain=<path>` → the same shape or 404

- [ ] **Step 1: Write the failing test**

Create `orchestrator/tests/test_charter_route.py`:

```python
# ABOUTME: POST /charter writes an expert's declaration into the three existing slots.
# ABOUTME: Domain row, alias merge-map rows, and an authored spec — atomically.

import os
import pytest

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

CHARTER = {
    "domain": "business/legal-compliance/contracts",
    "aliases": ["Legal/Contracts", "contracts", "legal/agreements"],
    "spec": "# Contract extraction\nExtract Party, Obligation, Termination Trigger.",
}


def test_charter_creates_domain_row(test_client, test_store):
    r = test_client.post("/charter", json=CHARTER)
    assert r.status_code == 201
    domain = test_store.domains.get("business/legal-compliance/contracts")
    assert domain is not None
    assert domain.parent_path == "business/legal-compliance"


def test_charter_writes_lowercased_aliases(test_store, test_client):
    test_client.post("/charter", json=CHARTER)
    rows = dict(test_store.conn.execute(
        "SELECT from_label, to_path FROM domain_merge_map").fetchall())
    assert rows["legal/contracts"] == "business/legal-compliance/contracts"
    assert rows["contracts"] == "business/legal-compliance/contracts"
    assert "Legal/Contracts" not in rows, "aliases must be stored normalised"


def test_charter_alias_is_resolved_by_the_normalizer(test_store, test_client):
    """The whole point: a classifier inventing `legal/contracts` folds onto the canonical path."""
    from src.pipeline.domain_normalizer import normalize_domain_label
    test_client.post("/charter", json=CHARTER)
    assert normalize_domain_label(test_store, "legal/contracts") == \
        "business/legal-compliance/contracts"


def test_charter_writes_authored_spec(test_store, test_client):
    test_client.post("/charter", json=CHARTER)
    spec = test_store.specs.get_for_domain("business/legal-compliance/contracts")
    assert spec.source == "authored"
    assert spec.version == 1
    assert "Termination Trigger" in spec.spec_content


def test_charter_sets_spec_version_to_disable_auto_simmer(test_store, test_client):
    """ingest.py only queues simmer_domain when spec_version IS NULL. Setting it is how
    an authored spec is protected from being silently replaced."""
    test_client.post("/charter", json=CHARTER)
    assert test_store.domains.get("business/legal-compliance/contracts").spec_version == 1


def test_second_charter_bumps_the_version(test_store, test_client):
    test_client.post("/charter", json=CHARTER)
    revised = {**CHARTER, "spec": "# Revised\nExtract Party only."}
    r = test_client.post("/charter", json=revised)
    assert r.status_code == 201
    spec = test_store.specs.get_for_domain("business/legal-compliance/contracts")
    assert spec.version == 2
    assert spec.spec_content == "# Revised\nExtract Party only."


def test_alias_equal_to_the_domain_is_skipped(test_store, test_client):
    """A self-referential merge row would make normalize_domain_label loop back on itself."""
    test_client.post("/charter", json={
        **CHARTER, "aliases": ["business/legal-compliance/contracts"]})
    rows = test_store.conn.execute("SELECT COUNT(*) AS c FROM domain_merge_map").fetchone()["c"]
    assert rows == 0


def test_get_charter_returns_it(test_client):
    test_client.post("/charter", json=CHARTER)
    r = test_client.get("/charter", params={"domain": "business/legal-compliance/contracts"})
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == "business/legal-compliance/contracts"
    assert sorted(body["aliases"]) == ["contracts", "legal/agreements", "legal/contracts"]
    assert "Termination Trigger" in body["spec"]


def test_get_charter_404s_when_absent(test_client):
    r = test_client.get("/charter", params={"domain": "nope/nothing"})
    assert r.status_code == 404


def test_charter_returns_201_with_location(test_client):
    """Project convention, locked in by tests/test_rest_hygiene.py: creation endpoints
    return 201 Created with a Location header, not a bare 200."""
    r = test_client.post("/charter", json=CHARTER)
    assert r.status_code == 201
    assert r.headers.get("Location") == \
        "/charter?domain=business%2Flegal-compliance%2Fcontracts"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd orchestrator && pytest tests/test_charter_route.py -v`
Expected: FAIL — all requests 404, the route does not exist.

- [ ] **Step 3: Add the request model**

In `orchestrator/src/models.py`, after `DryRunResult`:

```python
class CharterRequest(BaseModel):
    domain: str
    aliases: list[str] = []
    spec: str
```

- [ ] **Step 4: Write the route**

Create `orchestrator/src/routes/charter.py`:

```python
# ABOUTME: POST/GET /charter — a domain expert's declaration of their domain and rules.
# ABOUTME: Writes the domain row, alias merge-map rows, and an authored spec in one transaction.

import uuid
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..dependencies import get_auth_store, AuthStore
from ..models import CharterRequest

router = APIRouter()


@router.post("/charter", status_code=status.HTTP_201_CREATED)
async def create_charter(request: CharterRequest, response: Response,
                         auth: AuthStore = Depends(get_auth_store)):
    """Bind an expert's opinion into the pipeline.

    Three declarations, three existing slots:
      - the canonical domain path      -> `domains`, so the classifier sees it from document 1
      - the names that mean the same   -> `domain_merge_map`, checked FIRST by normalize_domain_label
      - the extraction rules           -> `specs` with source='authored'

    The domain row is written BEFORE the alias rows on purpose: `domain_merge_map.to_path`
    references `domains(path)`, and `normalize_domain_label` returns `to_path` without
    checking that the domain exists.
    """
    store = auth.store
    domain = request.domain.strip()
    if not domain:
        raise HTTPException(status_code=400, detail="domain must not be empty")
    if not request.spec.strip():
        raise HTTPException(status_code=400, detail="spec must not be empty")

    conn = store.conn

    # 1. Canonical domain row (created first — the alias rows point at it)
    if store.domains.get(domain) is None:
        parent_path = "/".join(domain.split("/")[:-1]) or None
        store.domains.create(str(uuid.uuid4()), domain, parent_path)

    # 2. Aliases. Both lookup paths normalise with .lower().strip(), so the stored key must
    # match or it will never resolve. A self-referential row is skipped.
    aliases_written = 0
    for alias in request.aliases:
        key = alias.lower().strip()
        if not key or key == domain.lower():
            continue
        conn.execute(
            "INSERT OR REPLACE INTO domain_merge_map (from_label, to_path) VALUES (?, ?)",
            (key, domain),
        )
        aliases_written += 1

    # 3. The authored spec
    version = store.specs.get_latest_version(domain) + 1
    store.specs.create(str(uuid.uuid4()), domain, version, request.spec, source="authored")

    # 4. Setting spec_version is what stops ingest.py from ever auto-queueing a
    # simmer_domain job over this domain — its guard is `spec_version IS NULL`. This is
    # how an authored spec is protected from being silently replaced.
    store.domains.update_spec_version(domain, version)

    conn.commit()
    # 201 + Location is the project convention for creation endpoints, locked in by
    # tests/test_rest_hygiene.py.
    response.headers["Location"] = f"/charter?domain={quote(domain, safe='')}"
    return {"domain": domain, "aliases_written": aliases_written, "spec_version": version}


@router.get("/charter")
async def get_charter(domain: str, auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    spec = store.specs.get_for_domain(domain)
    if not spec or spec.source != "authored":
        raise HTTPException(status_code=404, detail=f"No charter for domain: {domain}")
    aliases = [r["from_label"] for r in store.conn.execute(
        "SELECT from_label FROM domain_merge_map WHERE to_path = ?", (domain,)).fetchall()]
    return {"domain": domain, "aliases": aliases,
            "spec": spec.spec_content, "spec_version": spec.version}
```

- [ ] **Step 5: Register the router**

In `orchestrator/src/main.py`, alongside the other route imports add `from .routes.charter import router as charter_router`, and after `app.include_router(corrections_router)`:

```python
app.include_router(charter_router)
```

- [ ] **Step 6: Run the tests**

Run: `cd orchestrator && pytest tests/test_charter_route.py -v`
Expected: PASS (10 tests)

- [ ] **Step 7: Run the full suite**

Run: `cd orchestrator && pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add orchestrator/src/routes/charter.py orchestrator/src/models.py \
        orchestrator/src/main.py orchestrator/tests/test_charter_route.py
git commit -m "feat(charter): add POST/GET /charter binding an expert's declaration"
```

---

### Task 6: Authored-seed mode for `simmer_domain`

Refinement of an authored spec must keep the complete contract. If the refined output is stored as simmered, the general pass switches back on and the user's exclusions silently stop working.

**Files:**
- Modify: `worker/src/jobs/simmer_domain.py:45-92` (seed construction), `:143-151` (discovery early-return), `:166-185` (storage)
- Test: `worker/tests/test_simmer_authored_seed.py` (create)

**Interfaces:**
- Consumes: `specs.source` from Task 1
- Produces: no new public interface; `simmer_domain` behaviour becomes conditional on an existing authored spec

- [ ] **Step 1: Write the failing test**

Create `worker/tests/test_simmer_authored_seed.py`:

```python
# ABOUTME: Refining an authored spec must preserve the authored CONTRACT.
# ABOUTME: A refined spec stored as 'simmered' would silently re-enable the general pass.

import os
import pytest

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db, get_connection
from src.jobs.simmer_domain import _build_seed_content, _authored_spec_for


def _db_with_authored_spec(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, source) "
        "VALUES ('s1', 'legal/contracts', 1, '# My rules\nExtract Party and Obligation.', 'authored')")
    conn.commit()
    return db_path, conn


def test_authored_spec_is_detected(tmp_path):
    _, conn = _db_with_authored_spec(tmp_path)
    assert _authored_spec_for(conn, "legal/contracts") == \
        "# My rules\nExtract Party and Obligation."
    conn.close()


def test_no_authored_spec_returns_none(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, source) "
        "VALUES ('s1', 'legal/contracts', 1, 'simmered content', 'simmered')")
    conn.commit()
    assert _authored_spec_for(conn, "legal/contracts") is None
    conn.close()


def test_authored_seed_uses_the_users_rules_and_says_complete(tmp_path):
    seed = _build_seed_content(
        "legal/contracts", general_spec=None, authored_spec="# My rules\nExtract Party.")
    assert "# My rules" in seed
    assert "Extract Party." in seed
    assert "COMPLETE" in seed, "the seed must state the complete (non-additive) contract"
    assert "Add entity types specific to" not in seed, "must not use the additive framing"


def test_unauthored_seed_keeps_the_additive_framing(tmp_path):
    seed = _build_seed_content(
        "legal/contracts", general_spec="GENERAL SPEC BODY", authored_spec=None)
    assert "GENERAL SPEC BODY" in seed
    assert "Add entity types specific to legal/contracts" in seed
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd worker && pytest tests/test_simmer_authored_seed.py -v`
Expected: FAIL — `ImportError: cannot import name '_build_seed_content'`

- [ ] **Step 3: Extract the seed builder and the authored lookup**

In `worker/src/jobs/simmer_domain.py`, add these module-level functions above the job entry point:

```python
def _authored_spec_for(conn, domain_path: str) -> str | None:
    """Return the latest AUTHORED spec body for this domain, or None.

    Only authored specs are returned. A simmered spec is additive and is not a seed —
    seeding from one would just re-refine what the last run already produced.
    """
    row = conn.execute(
        "SELECT spec_content, source FROM specs WHERE domain_path = ? "
        "ORDER BY version DESC LIMIT 1", (domain_path,)).fetchone()
    if not row or (row[1] or "simmered") != "authored":
        return None
    return row[0]


def _build_seed_content(domain_path: str, general_spec: str | None,
                        authored_spec: str | None) -> str:
    """Build the golden-set seed.

    Two contracts, two framings, and they must not be mixed up:

      - AUTHORED: a domain expert has declared the entity types. Their types are FIXED;
        simmer refines only the wording and the examples. The spec stays COMPLETE, because
        an authored spec suppresses the general extraction pass (see
        orchestrator/src/pipeline/extraction_plan.py) and must therefore stand alone.
      - Otherwise: the historical additive framing — discover MORE GRANULAR types on top of
        the general spec, which still runs alongside.
    """
    reference_block = """## Reference Entities

Read every sample document and list ALL entities you find. Each entity must actually
appear in at least one sample document — do not invent entities.

Format as a JSON array:
```json
[
  {"name": "entity name lowercase", "type": "EntityType"},
  ...
]
```"""

    if authored_spec:
        return f"""# Golden Set — Domain: {domain_path}

## Entity Type Taxonomy
A domain expert authored the extraction rules below. This spec is COMPLETE: it is the only
spec that runs for this domain, so it must stand alone. Do NOT add entity types the expert
did not declare, and do NOT remove any they did. Refine only the wording, the boundaries,
and the examples.

{authored_spec}

{reference_block}"""

    if general_spec:
        return f"""# Golden Set — Domain: {domain_path}

## Entity Type Taxonomy
Starting from the general extraction spec, extend with domain-specific types:

{general_spec}

Add entity types specific to {domain_path} that the general spec misses.
Keep the general types but add domain-specific ones.

{reference_block}

Be thorough — every named person, organization, product, concept, place, and event
mentioned in the sample documents should appear here."""

    return f"""# Golden Set — Domain: {domain_path}

## Entity Type Taxonomy
- Discover what entity types matter for this specific domain
- Be more specific than generic types like Person, Organization, Thing

{reference_block}"""
```

- [ ] **Step 4: Run the new tests**

Run: `cd worker && pytest tests/test_simmer_authored_seed.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Use the helpers in the job body**

In `worker/src/jobs/simmer_domain.py`, replace the block at `:45-92` (from `# Get the general spec to use as starting point` through the end of the `else:` seed string) with:

```python
    authored_spec = _authored_spec_for(conn, domain_path)
    general_row = conn.execute(
        "SELECT spec_content FROM specs WHERE domain_path IS NULL ORDER BY version DESC LIMIT 1"
    ).fetchone()
    seed_content = _build_seed_content(
        domain_path,
        general_spec=general_row[0] if general_row else None,
        authored_spec=authored_spec,
    )
```

- [ ] **Step 6: Skip type discovery when the types are already declared**

Replace the discovery block at `:143-151` with:

```python
        if authored_spec:
            # The expert declared the types. There is nothing to discover, and the
            # early-return below (which exists to avoid storing a redundant generic spec)
            # must not fire — an authored refinement always has something to refine.
            domain_taxonomy = authored_spec
        else:
            domain_types = await _discover_domain_types(sample_chunks, domain_path, settings, db_path)
            n_domain = len(domain_types.splitlines()) if domain_types else 0
            print(f"Domain types for {domain_path}: +{n_domain}\n{domain_types}", flush=True)
            if not domain_types:
                # Nothing domain-specific to add → domain refinement has no value here. Skip
                # rather than store a generic spec that just re-does the base types the
                # general pass covers.
                print(f"No domain-specific types discovered for {domain_path}; skipping domain refinement.", flush=True)
                return
            domain_taxonomy = domain_types
```

- [ ] **Step 7: Preserve the source on write**

Replace the INSERT at `:176-179` with:

```python
    # The refined spec INHERITS the authored contract. Storing it as 'simmered' would flip
    # the general pass back on and silently undo the expert's exclusions.
    spec_source = "authored" if authored_spec else "simmered"
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (spec_id, domain_path, version, spec_content, golden_best, spec_score, spec_source),
    )
```

- [ ] **Step 8: Run the worker suite**

Run: `cd worker && pytest tests/ -q`
Expected: PASS, including `test_simmer_core.py` (the simmer invariants) and `test_simmer_wiring.py`

- [ ] **Step 9: Commit**

```bash
git add worker/src/jobs/simmer_domain.py worker/tests/test_simmer_authored_seed.py
git commit -m "feat(simmer): seed domain refinement from an authored spec and keep its contract"
```

---

### Task 7: The charter conversation skill

**Files:**
- Create: `.claude/skills/design-my-domain/SKILL.md`

**Interfaces:**
- Consumes: `POST /ingest?dry_run=true` (Task 4), `POST /charter` (Task 5)
- Produces: no code interface

- [ ] **Step 1: Write the skill**

Create `.claude/skills/design-my-domain/SKILL.md`:

```markdown
---
name: design-my-domain
description: Use when a Noospheric Orrery user is an expert in one domain (contracts, clinical notes, incident reports) and wants their own judgment to govern classification and extraction from the first document, instead of the generic spec. Runs a guided conversation over one of their real documents and writes a charter.
---

# Design My Domain

Turn a domain expert's opinion into a charter the pipeline obeys from document one.

## Why this exists

The classifier's reference vocabulary (`orchestrator/specs/taxonomy.json`) has 199 topics, 107
of them software. A lawyer's entire field is four topics. Off-taxonomy users get invented domain
paths that fragment across near-duplicates, so `document_count` never reaches the 20 needed to
trigger a domain simmer — they can wait forever and never get a spec.

A charter skips all of that: it declares the domain, the aliases that fold onto it, and the
extraction spec, so extraction is right on the first document.

## The one rule

**Never ask the user to write an ontology from a blank form.** Experts critique output fluently
and prompts not at all. Show them what the system would actually do, and let them correct it.

## Process

### 1. Ask what they work on

One question, free text. "Contracts — mostly NDAs and MSAs."

### 2. Look for an existing home in the taxonomy

Read `orchestrator/specs/taxonomy.json` and find the closest existing path.
`business/legal-compliance/contracts` already exists.

**Propose reusing it.** Reuse is what lets their content merge with everything else in the
graph. Inventing a new top-level region is the failure mode, not the feature. Only propose a
new path if nothing in the file is close.

### 3. Ask them to drop in one real document

A real one, not a sample you invent. The whole method depends on them reacting to their own
material.

### 4. Dry-run it

    curl -s -X POST "$ORRERY_API/ingest?dry_run=true" -F "file=@<their-file>"

This classifies and extracts and writes nothing.

### 5. Show them the first pass

Present exactly two things:

- **"I'd file this as `<primary_domain>`"** — plus any secondaries
- **"I'd extract these types"** — every type with its count and 2-3 real instances from
  their document

Show the instances. `Date — 47 instances: "January 3, 2024", "the 15th day", "upon signing"`
provokes a useful reaction; `Date — 47` does not.

### 6. Collect their corrections

Two questions, asked separately:

- **Is the path right?** What other names should fold onto it? Their answer becomes `aliases`.
  Push for the near-duplicates a classifier would plausibly invent — `legal/contracts`,
  `contracts`, `legal/agreements`.
- **Which types matter?** What is noise, what is missing entirely? Their answer becomes the
  spec.

### 7. Validate on a second document

Not optional. The first round always overfits to one sample. Dry-run a second document and
show what their corrected type list would have missed.

### 8. Run the worth-it analysis

Compare their corrected type set against what the general spec actually produced:

- **`added`** — types they want that the general spec never emitted
- **`dropped`** — types it emitted that they rejected
- **`kept`** — the overlap

Then recommend:

- **`added` is non-empty → write the charter.** The general spec structurally cannot produce
  those types. Waiting does not fix it.
- **`added` empty but `dropped` > half → write the charter.** An authored spec replaces the
  general pass, so the noise genuinely disappears.
- **Otherwise → recommend the general spec and write nothing.** Say it plainly: "your edits
  were minor, the general spec already covers this, a charter is maintenance you don't need."

**Be willing to reach the third conclusion.** A skill that always recommends its own artifact
is useless as advice.

### 9. Show the charter and get explicit confirmation

Print the full payload. Nothing is written until they say yes.

    curl -s -X POST "$ORRERY_API/charter" -H 'Content-Type: application/json' -d '{
      "domain": "business/legal-compliance/contracts",
      "aliases": ["legal/contracts", "contracts", "legal/agreements"],
      "spec": "# Contract extraction\n..."
    }'

## What the charter does once written

- Their domain appears in the classifier's existing-taxonomy block from the next document
- Aliases fold the classifier's inventions onto their canonical path automatically
- Their spec runs **instead of** the general pass for documents in that domain
- Auto-simmer is disabled for the domain, so their spec is never silently replaced.
  `POST /simmer/<domain>` refines it on request, seeded from what they wrote.

## Writing the spec itself

Match the shape of `orchestrator/specs/general_text.md`. It must be **complete and
self-contained** — it is the only spec that will run for that domain, so anything it omits is
not extracted at all. This is the opposite of a simmered domain spec, which is additive.
```

- [ ] **Step 2: Verify the skill is discoverable**

Run: `ls .claude/skills/design-my-domain/SKILL.md`
Expected: the file exists, with valid YAML frontmatter containing `name` and `description`

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/design-my-domain/SKILL.md
git commit -m "feat(skill): add design-my-domain charter conversation"
```

---

## Final verification

- [ ] `cd orchestrator && pytest tests/ -v` — all pass
- [ ] `cd worker && pytest tests/ -v` — all pass
- [ ] `git diff main --stat -- orchestrator/tests/test_ingest_route.py` shows **no changes** (the no-opinion guarantee)
- [ ] Manual end-to-end: start the stack, `POST /charter`, ingest a matching document, confirm `entity_sources.extraction_pass` is only `domain-specific`; ingest a non-matching document, confirm it is `general`
