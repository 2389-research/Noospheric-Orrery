# Section-Stratified Research Paper Extraction Spec Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the flat `orchestrator/specs/domain_research_paper.md` extraction spec into per-section files (introduction/related_work/method/experiments/conclusion/abstract/default) so a weaker extraction model gets section-appropriate rules, and add a standalone CLI script for iterating on each section's spec against real PDFs.

**Architecture:** A new `section_splitter.py` labels spans of a paper's text by section (heuristic heading regex + a single LLM fallback call for unlabeled stretches). Chunking runs per-span so no chunk crosses a section boundary, and each chunk record carries a `section` label. `extractor.py` gains a section-aware extraction function that composes `shared.md + <section>.md` per chunk. `ingest.py`'s domain cascade uses this for the `research_paper` domain specifically, with a built-in fallback (mirroring how `GENERAL_TEXT_SPEC` already works) when no simmered override exists yet. A standalone script exercises the whole thing against the raw PDFs already sitting in `pi0/papers/`.

**Tech Stack:** Python, FastAPI (orchestrator), SQLite (WAL mode), pytest + pytest-asyncio, `orrery_relay.Relay`, `pypdf` (already a dependency, used by `file_extractor.py`).

## Global Constraints

- Every new SQLite connection must set `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout` — already handled by `get_connection()`, don't open raw `sqlite3.connect` elsewhere.
- Orchestrator and worker `db.py` schemas must stay identical (per `CLAUDE.md`) — any migration added to one must be mirrored in the other, in the same `init_db` migration style (check `PRAGMA table_info`, `ALTER TABLE ... ADD COLUMN` if missing).
- All Claude API calls go through `Relay.from_settings(settings)` — never instantiate an Anthropic client directly.
- Model names used in code must be the friendly names (`claude-sonnet-4-6`, `claude-haiku-4-5`, etc.), pulled from `Settings`, never hardcoded.
- Domain path format uses `/` as a hierarchical separator — not relevant to section names (section names are flat, e.g. `"introduction"`, `"method"`), but don't conflate the two concepts in code or naming.
- `pipeline/` modules must stay pure functions with no FastAPI coupling — `section_splitter.py` takes a `Relay` as a parameter, it does not construct one.

---

### Task 1: Section splitter — heuristic heading detection

**Files:**
- Create: `orchestrator/src/pipeline/section_splitter.py`
- Test: `orchestrator/tests/test_section_splitter.py`

**Interfaces:**
- Produces: `KNOWN_SECTIONS: list[str]` = `["abstract", "introduction", "related_work", "method", "experiments", "conclusion"]`
- Produces: `find_headings(text: str) -> list[dict]` — each dict is `{"section": str, "start": int}`, one entry per detected heading line, in ascending `start` order. `section` is one of `KNOWN_SECTIONS`.

- [ ] **Step 1: Write the failing tests**

```python
# orchestrator/tests/test_section_splitter.py
from src.pipeline.section_splitter import find_headings, KNOWN_SECTIONS


def test_finds_markdown_style_headings():
    text = "intro text\n\n## Introduction\n\nWe propose X.\n\n## Related Work\n\nPrior work Y.\n"
    headings = find_headings(text)
    sections = [h["section"] for h in headings]
    assert sections == ["introduction", "related_work"]


def test_finds_numbered_headings():
    text = "1. Introduction\nWe propose X.\n\n2. Related Work\nPrior work Y.\n\n3. Method\nOur approach.\n"
    headings = find_headings(text)
    assert [h["section"] for h in headings] == ["introduction", "related_work", "method"]


def test_finds_roman_numeral_headings_case_insensitive():
    text = "IV. EXPERIMENTS\nWe ran experiments.\n\nV. CONCLUSION\nWe conclude.\n"
    headings = find_headings(text)
    assert [h["section"] for h in headings] == ["experiments", "conclusion"]


def test_ignores_heading_keyword_inside_a_sentence():
    text = "This paper's introduction motivates the problem before the related work section.\n"
    headings = find_headings(text)
    assert headings == []


def test_headings_are_ascending_by_start_offset():
    text = "## Abstract\nA.\n\n## Method\nB.\n"
    headings = find_headings(text)
    assert headings[0]["start"] < headings[1]["start"]
    assert headings[0]["section"] == "abstract"


def test_known_sections_list_is_stable():
    assert KNOWN_SECTIONS == [
        "abstract", "introduction", "related_work", "method",
        "experiments", "conclusion",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_section_splitter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.pipeline.section_splitter'`

- [ ] **Step 3: Implement `find_headings`**

```python
# orchestrator/src/pipeline/section_splitter.py
# ABOUTME: Splits a research paper's full text into section-labeled spans.
# ABOUTME: Heuristic heading detection with an LLM fallback for unclassified stretches.

import re

KNOWN_SECTIONS = ["abstract", "introduction", "related_work", "method", "experiments", "conclusion"]

_SECTION_KEYWORDS = {
    "abstract": ["abstract"],
    "introduction": ["introduction"],
    "related_work": ["related work", "background"],
    "method": ["method", "methods", "methodology", "approach"],
    "experiments": ["experiments", "experiment", "results", "evaluation"],
    "conclusion": ["conclusion", "conclusions", "discussion", "limitations"],
}

# Matches a whole line that is *only* a heading: optional markdown hashes, optional
# numbering (arabic "1." or roman "IV."), then the keyword phrase, nothing else after it.
_NUMBERING = r"(?:#{1,3}\s*|\d+(?:\.\d+)*\.?\s+|[IVXLC]+\.\s+)?"


def _build_line_pattern(keyword: str) -> re.Pattern:
    return re.compile(rf"^\s*{_NUMBERING}{re.escape(keyword)}\s*$", re.IGNORECASE)


def find_headings(text: str) -> list[dict]:
    headings = []
    offset = 0
    for line in text.split("\n"):
        line_start = offset
        offset += len(line) + 1  # account for the '\n' split removed
        stripped = line.strip()
        if not stripped:
            continue
        for section, keywords in _SECTION_KEYWORDS.items():
            for keyword in keywords:
                if _build_line_pattern(keyword).match(stripped):
                    headings.append({"section": section, "start": line_start})
                    break
            else:
                continue
            break
    headings.sort(key=lambda h: h["start"])
    return headings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_section_splitter.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/section_splitter.py orchestrator/tests/test_section_splitter.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): add heuristic section heading detection

Detects Introduction/Related Work/Method/Experiments/Conclusion/
Abstract headings via markdown, numbered, and roman-numeral line
patterns. First step toward section-stratified research paper
extraction.
EOF
)"
```

---

### Task 2: Section spans — coverage + LLM fallback for unlabeled stretches

**Files:**
- Modify: `orchestrator/src/pipeline/section_splitter.py`
- Test: `orchestrator/tests/test_section_splitter.py`

**Interfaces:**
- Consumes: `find_headings(text) -> list[dict]` from Task 1.
- Consumes: `Relay.complete_structured(model, max_tokens, messages, schema, tool_name, tool_description) -> dict` (existing method, see `extractor.py` for usage pattern).
- Produces: `async def label_sections(relay, text: str, model: str) -> list[dict]` — returns `[{"section": str, "start": int, "end": int}]` covering `[0, len(text))` with no gaps or overlaps, in ascending order. `section` is one of `KNOWN_SECTIONS + ["unclassified"]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to orchestrator/tests/test_section_splitter.py
import pytest
from unittest.mock import AsyncMock
from src.pipeline.section_splitter import label_sections


def test_label_sections_covers_whole_document_no_headings():
    text = "word " * 50

    async def run():
        mock_relay = AsyncMock()
        mock_relay.complete_structured = AsyncMock(return_value={"section": "introduction"})
        spans = await label_sections(mock_relay, text, model="claude-haiku-4-5")
        assert spans[0]["start"] == 0
        assert spans[-1]["end"] == len(text)
        assert spans[0]["section"] == "introduction"
        mock_relay.complete_structured.assert_called_once()

    import asyncio
    asyncio.get_event_loop().run_until_complete(run())


@pytest.mark.asyncio
async def test_label_sections_splits_on_headings_no_llm_call_needed():
    text = "## Introduction\nWe propose X.\n\n## Method\nOur approach.\n"
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock()
    spans = await label_sections(mock_relay, text, model="claude-haiku-4-5")
    sections = [s["section"] for s in spans]
    assert sections == ["introduction", "method"]
    assert spans[0]["start"] == 0
    assert spans[-1]["end"] == len(text)
    # Consecutive spans are contiguous, no gaps/overlaps
    for prev, nxt in zip(spans, spans[1:]):
        assert prev["end"] == nxt["start"]
    mock_relay.complete_structured.assert_not_called()


@pytest.mark.asyncio
async def test_label_sections_llm_fallback_for_text_before_first_heading():
    text = "Some preamble that has no heading.\n\n## Method\nOur approach.\n"
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={"section": "abstract"})
    spans = await label_sections(mock_relay, text, model="claude-haiku-4-5")
    assert spans[0]["section"] == "abstract"
    assert spans[0]["start"] == 0
    assert spans[1]["section"] == "method"
    mock_relay.complete_structured.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_section_splitter.py -v -k label_sections`
Expected: FAIL with `ImportError: cannot import name 'label_sections'`

- [ ] **Step 3: Implement `label_sections`**

```python
# append to orchestrator/src/pipeline/section_splitter.py

_CLASSIFY_PROMPT = """Which section of a research paper does the following text most likely belong to?

Choose exactly one: abstract, introduction, related_work, method, experiments, conclusion, other

TEXT:
{excerpt}"""

_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "section": {
            "type": "string",
            "enum": KNOWN_SECTIONS + ["other"],
        },
    },
    "required": ["section"],
}


async def _classify_span(relay, text: str, model: str) -> str:
    excerpt = text[:1500]
    result = await relay.complete_structured(
        model=model, max_tokens=64,
        messages=[{"role": "user", "content": _CLASSIFY_PROMPT.format(excerpt=excerpt)}],
        schema=_CLASSIFY_SCHEMA,
        tool_name="classify_section",
        tool_description="Classify which research paper section a text excerpt belongs to",
    )
    section = result.get("section", "other")
    return section if section in KNOWN_SECTIONS else "unclassified"


async def label_sections(relay, text: str, model: str) -> list[dict]:
    headings = find_headings(text)
    doc_len = len(text)

    # Build raw spans between consecutive headings (and before the first / there are none)
    boundaries = [h["start"] for h in headings] + [doc_len]
    raw_spans = []
    if not headings:
        raw_spans.append({"section": None, "start": 0, "end": doc_len})
    else:
        if headings[0]["start"] > 0:
            raw_spans.append({"section": None, "start": 0, "end": headings[0]["start"]})
        for i, heading in enumerate(headings):
            raw_spans.append({
                "section": heading["section"],
                "start": heading["start"],
                "end": boundaries[i + 1],
            })

    spans = []
    for span in raw_spans:
        if span["section"] is None:
            span_text = text[span["start"]:span["end"]]
            span["section"] = await _classify_span(relay, span_text, model) if span_text.strip() else "unclassified"
        spans.append(span)
    return spans
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_section_splitter.py -v`
Expected: PASS (all 9 tests — note: add `pytest.mark.asyncio` decorator consistently; the first fallback test above uses `asyncio.get_event_loop().run_until_complete` only to illustrate — replace it with `@pytest.mark.asyncio async def` matching the other two for consistency before running)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/section_splitter.py orchestrator/tests/test_section_splitter.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): add LLM fallback for unclassified section spans

label_sections() covers the whole document with contiguous spans,
using heading regex first and a single classify call per unheaded
stretch (not per chunk) as fallback.
EOF
)"
```

---

### Task 3: Section-aware chunking wrapper

**Files:**
- Modify: `orchestrator/src/pipeline/chunker.py`
- Test: `orchestrator/tests/test_chunker.py`

**Interfaces:**
- Consumes: `chunk_document(text, chunk_size, overlap) -> list[dict]` (existing, unchanged).
- Consumes: `label_sections(relay, text, model) -> list[dict]` from Task 2.
- Produces: `async def chunk_by_sections(relay, text: str, model: str, chunk_size: int = 2000, overlap: int = 200) -> list[dict]` — same dict shape as `chunk_document` output (`chunk_index`, `offset`, `length`, `text`) plus a new `"section"` key, with `chunk_index` and `offset` continuous across the whole document (not reset per section) and `offset`/`length` still relative to the full original `text`.

- [ ] **Step 1: Write the failing test**

```python
# append to orchestrator/tests/test_chunker.py
import pytest
from unittest.mock import AsyncMock
from src.pipeline.chunker import chunk_by_sections


@pytest.mark.asyncio
async def test_chunk_by_sections_tags_each_chunk_and_preserves_offsets():
    text = "## Introduction\n" + ("intro word " * 300) + "\n\n## Method\n" + ("method word " * 300)
    mock_relay = AsyncMock()
    chunks = await chunk_by_sections(mock_relay, text, model="claude-haiku-4-5", chunk_size=500, overlap=50)

    assert len(chunks) > 1
    assert all("section" in c for c in chunks)
    assert chunks[0]["section"] == "introduction"
    assert chunks[-1]["section"] == "method"
    # chunk_index is continuous across the whole document
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    # offset/length still index into the ORIGINAL text
    for c in chunks:
        assert text[c["offset"]:c["offset"] + c["length"]] == c["text"]


@pytest.mark.asyncio
async def test_chunk_by_sections_no_headings_uses_llm_label_for_whole_doc():
    text = "word " * 300
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={"section": "method"})
    chunks = await chunk_by_sections(mock_relay, text, model="claude-haiku-4-5", chunk_size=500, overlap=50)
    assert all(c["section"] == "method" for c in chunks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_chunker.py -v -k chunk_by_sections`
Expected: FAIL with `ImportError: cannot import name 'chunk_by_sections'`

- [ ] **Step 3: Implement `chunk_by_sections`**

```python
# append to orchestrator/src/pipeline/chunker.py
from .section_splitter import label_sections


async def chunk_by_sections(relay, text: str, model: str, chunk_size: int = 2000, overlap: int = 200) -> list[dict]:
    spans = await label_sections(relay, text, model)
    all_chunks = []
    idx = 0
    for span in spans:
        span_text = text[span["start"]:span["end"]]
        if not span_text:
            continue
        for chunk in chunk_document(span_text, chunk_size=chunk_size, overlap=overlap):
            all_chunks.append({
                "chunk_index": idx,
                "offset": span["start"] + chunk["offset"],
                "length": chunk["length"],
                "text": chunk["text"],
                "section": span["section"],
            })
            idx += 1
    return all_chunks
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_chunker.py -v`
Expected: PASS (all tests, including the 3 pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/chunker.py orchestrator/tests/test_chunker.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): add section-aware chunking wrapper

chunk_by_sections() chunks within each detected section span so no
chunk straddles a section boundary, tagging each chunk with its
section while keeping chunk_index/offset continuous over the whole
document.
EOF
)"
```

---

### Task 4: `section` column on `chunks` table (orchestrator + worker)

**Files:**
- Modify: `orchestrator/src/db.py`
- Modify: `worker/src/db.py`
- Modify: `orchestrator/src/repositories/interfaces.py`
- Modify: `orchestrator/src/repositories/sqlite_store.py`
- Test: `orchestrator/tests/test_db.py`

**Interfaces:**
- Produces: `Chunk` dataclass gains `section: str | None = None`.
- Produces: `ChunkRepository.create_batch` and `get_for_document` persist/return `section`.

- [ ] **Step 1: Write the failing test**

```python
# append to orchestrator/tests/test_db.py — check existing imports at top of file first and reuse them
def test_chunks_table_has_section_column(tmp_path):
    from src.db import init_db
    import sqlite3
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chunks)").fetchall()}
    assert "section" in cols
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && pytest tests/test_db.py -v -k section_column`
Expected: FAIL with `AssertionError`

- [ ] **Step 3: Add the migration to orchestrator/src/db.py**

In `orchestrator/src/db.py`, inside `init_db`, right after the existing chunks-table migration block (`if "image_embedding" not in chunk_cols: ...`):

```python
            if "section" not in chunk_cols:
                conn.execute("ALTER TABLE chunks ADD COLUMN section TEXT")
```

- [ ] **Step 4: Mirror the same migration in worker/src/db.py**

Find the equivalent chunk migration block in `worker/src/db.py` (near line 204, `conn.execute("ALTER TABLE chunks ADD COLUMN image_embedding BLOB")`) and add directly after it, following the same `PRAGMA table_info` / `if col not in cols` guard pattern already used in that file:

```python
        if "section" not in cols:
            conn.execute("ALTER TABLE chunks ADD COLUMN section TEXT")
```

(Match whatever variable name that file's `chunks` `PRAGMA table_info` result is already assigned to — read the surrounding ~15 lines before editing to use the correct variable name instead of introducing a duplicate query.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd orchestrator && pytest tests/test_db.py -v -k section_column`
Expected: PASS

- [ ] **Step 6: Update `Chunk` dataclass and repository methods**

In `orchestrator/src/repositories/interfaces.py`, update the `Chunk` dataclass:

```python
@dataclass
class Chunk:
    id: str
    document_id: str
    chunk_index: int
    text: str
    offset: int = 0
    length: int = 0
    embedding: bytes | None = None
    section: str | None = None
```

In `orchestrator/src/repositories/sqlite_store.py`, update `SQLiteChunkRepository`:

```python
    def create_batch(self, chunks):
        for c in chunks:
            self._conn.execute(
                "INSERT INTO chunks (id, document_id, chunk_index, offset, length, text, section) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (c.id, c.document_id, c.chunk_index, c.offset, c.length, c.text, c.section),
            )
        self._conn.commit()

    def get_for_document(self, doc_id):
        rows = self._conn.execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index", (doc_id,)
        ).fetchall()
        return [Chunk(id=r["id"], document_id=r["document_id"], chunk_index=r["chunk_index"],
                       text=r["text"], offset=r["offset"], length=r["length"],
                       embedding=r["embedding"], section=r["section"]) for r in rows]
```

- [ ] **Step 7: Write and run a repository round-trip test**

```python
# append to orchestrator/tests/test_db.py
def test_chunk_repository_round_trips_section(tmp_path):
    from src.db import init_db, get_connection
    from src.repositories.sqlite_store import SQLiteChunkRepository, SQLiteDocumentRepository
    from src.repositories.interfaces import Chunk
    import uuid

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    doc_repo = SQLiteDocumentRepository(conn)
    doc_id = str(uuid.uuid4())
    doc_repo.create(doc_id, "Test Doc", "some content", "hash123", None)

    chunk_repo = SQLiteChunkRepository(conn)
    chunk_id = str(uuid.uuid4())
    chunk_repo.create_batch([Chunk(id=chunk_id, document_id=doc_id, chunk_index=0,
                                    text="intro text", offset=0, length=10, section="introduction")])

    chunks = chunk_repo.get_for_document(doc_id)
    assert chunks[0].section == "introduction"
```

Run: `cd orchestrator && pytest tests/test_db.py -v`
Expected: PASS (check `SQLiteDocumentRepository.create`'s exact positional signature in `sqlite_store.py` before writing this test — adjust arguments to match if it differs)

- [ ] **Step 8: Commit**

```bash
git add orchestrator/src/db.py worker/src/db.py orchestrator/src/repositories/interfaces.py orchestrator/src/repositories/sqlite_store.py orchestrator/tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(db): add section column to chunks table

Mirrors the migration in both orchestrator and worker db.py per the
project's shared-schema requirement. Chunk dataclass and
SQLiteChunkRepository now carry the section label produced by
chunk_by_sections().
EOF
)"
```

---

### Task 5: Reorganize `domain_research_paper.md` into per-section spec files

**Files:**
- Create: `orchestrator/specs/research_paper/shared.md`
- Create: `orchestrator/specs/research_paper/default.md`
- Create: `orchestrator/specs/research_paper/introduction.md`
- Create: `orchestrator/specs/research_paper/related_work.md`
- Create: `orchestrator/specs/research_paper/method.md`
- Create: `orchestrator/specs/research_paper/experiments.md`
- Create: `orchestrator/specs/research_paper/conclusion.md`
- Create: `orchestrator/specs/research_paper/abstract.md`
- Delete: `orchestrator/specs/domain_research_paper.md`

This task is a content migration, not a code change — there's no test to write/run; verify by reading the resulting files.

- [ ] **Step 1: Create `shared.md`**

Move the bulk of the existing `domain_research_paper.md` into `shared.md` unchanged: the purpose/design-principle intro, the full Entity Types table, the Type Decision Tree, Custom Type Constraints, the general "Extraction Rules" (`What to Extract` / `What NOT to Extract` items 1-6 that aren't section-specific — i.e. everything except item 3 "Tasks with a stated outcome" gets a note added, see Step 3), Entity Boundary Guidance, Entity Naming Rules, Worked Examples (keep all 3 as calibration reference), Output Schema, and Execution Notes. Keep the exact wording — this is a lossless move, verify with a manual diff against the original file before deleting it.

- [ ] **Step 2: Create `default.md`**

```markdown
# Research Paper Spec — Default / Unclassified Section

**When this applies:** the chunk's section could not be confidently classified (see
`section_splitter.py`). Apply the shared rules in `shared.md` with no additional
section-specific emphasis — treat this like a generic paper excerpt.
```

- [ ] **Step 3: Create `introduction.md`**

```markdown
# Research Paper Spec — Introduction Section

**Failure mode this guards against:** Introductions restate the hero model/task in loose,
promotional prose before the paper's precise terminology is established. A weaker extraction
model tends to over-extract vague capability claims as `task` entities here.

**Extra scrutiny for this section:**

- Apply "What NOT to Extract" #2 from `shared.md` (vague capability claims) more strictly than
  elsewhere: if a capability is described in general terms ("perform long-horizon tasks in new
  environments") without a *specific, nameable* task alongside it in the same sentence or the
  next, skip it — even if it sounds important. Wait for the Experiments section, where the same
  capability will be restated as a concrete evaluated task.
- The paper's own hero model IS worth extracting here (it's usually named for the first time in
  the introduction) — do not suppress `model` extraction, only `task` extraction, per the rule
  above.
- Named baseline/prior-work models mentioned in passing ("unlike prior methods such as X") ARE
  still real `model` entities if named — this section's caution is about vague tasks, not about
  under-extracting models.
```

- [ ] **Step 4: Create `related_work.md`**

```markdown
# Research Paper Spec — Related Work Section

**Failure mode this guards against:** This section is citation-dense. A weaker extraction model
tends to over-extract every cited paper's model/method name as if it were being actively
compared, when most citations here are just background scaffolding.

**Extra scrutiny for this section:**

- Apply `shared.md`'s citation-skip rule (What NOT to Extract, citation-adjacent names) to model
  and method names too, not just `person`/`organization`: if a model or method name appears only
  as "X [12] does Y" or "X (Smith et al., 2023)" with no further discussion beyond that one
  citation sentence, skip it — it's a citation, not a comparison baseline.
- DO extract a cited model/method if the paper discusses it across 2+ sentences (e.g. contrasts
  its approach against the current paper's approach) — that crosses from "citation" to "prior
  work being meaningfully discussed," which is real content for the graph.
```

- [ ] **Step 5: Create `method.md`**

```markdown
# Research Paper Spec — Method Section

**Failure mode this guards against:** This is the densest section for the `model` vs `method`
boundary (see `shared.md`'s Type Decision Tree #1) — training procedures, losses, and
architectural components are introduced together, and a weaker model tends to promote
sub-techniques to `model` status just because they're capitalized/acronymed.

**Extra scrutiny for this section:**

- Before extracting anything as `model`, check: does the paper evaluate THIS THING END-TO-END
  with its own results, or is it a component/procedure used to train or run the paper's actual
  model? If the latter, it's `method`, full stop — re-apply the Type Decision Tree #1 test
  explicitly per entity in this section, don't extract-then-sort.
- Named datasets introduced as training inputs belong here too (`dataset` type) — this section
  is where data composition is usually described in detail.
```

- [ ] **Step 6: Create `experiments.md`**

```markdown
# Research Paper Spec — Experiments/Results Section

**Failure mode this guards against:** this is where most of the graph-worthy `model`/`task`/
`platform`/`apparatus` content is concentrated (baseline comparisons, ablations, named tasks with
outcomes) — the risk here is under-extraction from a weak model getting overwhelmed by density,
not over-extraction.

**Extra scrutiny for this section:**

- Lean toward recall over precision in this section specifically (the opposite bias from
  Introduction/Related Work) — a comparison table or ablation list naming 5+ baselines in one
  sentence should yield 5+ `model` entities, not just the first one or two.
- Every named task with a stated outcome (`shared.md` What to Extract #3) should be extracted even
  when tasks are listed tersely as a comma-separated list ("laundry folding, box assembly, table
  bussing") — don't drop later items in a list because the sentence structure is repetitive.
- Named `platform`/`apparatus` entities are most likely to be named precisely here (specific rig
  names, specific appliances) — apply `shared.md`'s platform/apparatus decision tree per entity.
```

- [ ] **Step 7: Create `conclusion.md`**

```markdown
# Research Paper Spec — Conclusion Section

**Failure mode this guards against:** conclusions mostly restate entities already extracted from
earlier sections in summary form. The risk is duplicate near-identical extraction attempts
(harmless after dedup, but wasted extraction-call effort) and, more importantly, a weak model
inventing a NEW vague self-referential entity ("our approach," "this system") that isn't a real
addition to the graph.

**Extra scrutiny for this section:**

- Apply `shared.md`'s self-reference rule (What NOT to Extract #4) strictly — if the conclusion
  just re-describes the paper's own model/method without introducing a genuinely new named
  entity, extract nothing new from that sentence.
- Future-work mentions of *unbuilt* things ("we leave X to future work") are NOT entities unless
  X is itself a specific named technique/task that already appears elsewhere in the paper.
```

- [ ] **Step 8: Create `abstract.md`**

```markdown
# Research Paper Spec — Abstract Section

**Failure mode this guards against:** abstracts are extremely dense summaries — nearly every
noun phrase is a candidate entity, and a weak model can over-extract by treating the abstract
like normal prose instead of a compressed index of what the rest of the paper will elaborate.

**Extra scrutiny for this section:**

- Extract the paper's hero `model` and its 1-2 headline named `task`s/`method`s from the
  abstract — these are almost always genuinely introduced here.
- Do NOT extract every quantitative claim as a full `metric` string from the abstract alone if
  the same number reappears with more precision in Experiments — prefer the more precise later
  occurrence; a rough abstract-level restatement ("nearly halves the failure rate") is fine to
  extract once, just don't treat every subsequent partial restatement across sections as a new
  metric.
```

- [ ] **Step 9: Delete the old flat spec file**

```bash
git rm orchestrator/specs/domain_research_paper.md
```

- [ ] **Step 10: Manual verification**

Read `orchestrator/specs/research_paper/shared.md` end-to-end and confirm nothing from the
original `domain_research_paper.md` was dropped (the git history still has it at HEAD~ for a
diff): `git show HEAD:orchestrator/specs/domain_research_paper.md` vs the new `shared.md`.

- [ ] **Step 11: Commit**

```bash
git add orchestrator/specs/research_paper/
git commit -m "$(cat <<'EOF'
refactor(specs): split domain_research_paper.md into per-section files

shared.md carries the type definitions and rules that apply
everywhere; introduction/related_work/method/experiments/conclusion/
abstract/default.md each add only the guidance relevant to that
section's weak-model failure mode. See docs/superpowers/specs/
2026-07-29-research-paper-section-spec-design.md for the rationale.
EOF
)"
```

---

### Task 6: Section-aware extraction function

**Files:**
- Modify: `orchestrator/src/pipeline/extractor.py`
- Test: `orchestrator/tests/test_extractor.py`

**Interfaces:**
- Consumes: `extract_entities_from_chunk(relay, chunk_text, spec, model) -> list[dict]` (existing, unchanged).
- Produces: `async def extract_document_sectioned(relay, chunks: list[dict], section_specs: dict[str, str], model: str) -> list[dict]` — same behavior/output shape as `extract_document` (dedup by `(name.lower().strip(), type)`, each entity gets `chunk_id` set from `chunk.get("id")`), but the spec used per chunk is `section_specs.get(chunk.get("section"), section_specs["default"])`.

- [ ] **Step 1: Write the failing test**

```python
# append to orchestrator/tests/test_extractor.py
from src.pipeline.extractor import extract_document_sectioned


@pytest.mark.asyncio
async def test_extract_document_sectioned_picks_spec_by_chunk_section():
    mock_relay = AsyncMock()

    async def fake_complete_structured(model, max_tokens, messages, schema, tool_name, tool_description):
        prompt = messages[0]["content"]
        if "INTRO-ONLY-MARKER" in prompt:
            return {"entities": [{"name": "hero model", "type": "model"}]}
        return {"entities": [{"name": "some method", "type": "method"}]}

    mock_relay.complete_structured = AsyncMock(side_effect=fake_complete_structured)

    chunks = [
        {"id": "c1", "text": "We propose the hero model.", "section": "introduction"},
        {"id": "c2", "text": "The method combines two losses.", "section": "method"},
    ]
    section_specs = {
        "introduction": "INTRO-ONLY-MARKER extraction spec",
        "method": "method extraction spec",
        "default": "default extraction spec",
    }

    entities = await extract_document_sectioned(
        relay=mock_relay, chunks=chunks, section_specs=section_specs, model="claude-haiku-4-5",
    )

    assert {"name": "hero model", "type": "model", "chunk_id": "c1"} in entities
    assert {"name": "some method", "type": "method", "chunk_id": "c2"} in entities


@pytest.mark.asyncio
async def test_extract_document_sectioned_falls_back_to_default_for_unknown_section():
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={"entities": [{"name": "x", "type": "model"}]})
    chunks = [{"id": "c1", "text": "text", "section": "unclassified"}]
    section_specs = {"introduction": "intro spec", "default": "DEFAULT-MARKER spec"}

    await extract_document_sectioned(
        relay=mock_relay, chunks=chunks, section_specs=section_specs, model="claude-haiku-4-5",
    )

    call_kwargs = mock_relay.complete_structured.call_args.kwargs
    assert "DEFAULT-MARKER" in call_kwargs["messages"][0]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && pytest tests/test_extractor.py -v -k sectioned`
Expected: FAIL with `ImportError: cannot import name 'extract_document_sectioned'`

- [ ] **Step 3: Implement `extract_document_sectioned`**

```python
# append to orchestrator/src/pipeline/extractor.py
async def extract_document_sectioned(
    relay: Relay, chunks: list[dict], section_specs: dict[str, str], model: str,
) -> list[dict]:
    all_entities = []
    seen = set()
    for chunk in chunks:
        spec = section_specs.get(chunk.get("section"), section_specs["default"])
        entities = await extract_entities_from_chunk(relay=relay, chunk_text=chunk["text"], spec=spec, model=model)
        for entity in entities:
            key = (entity["name"].lower().strip(), entity["type"])
            if key not in seen:
                seen.add(key)
                entity["chunk_id"] = chunk.get("id")
                all_entities.append(entity)
    return all_entities
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && pytest tests/test_extractor.py -v`
Expected: PASS (all tests, including pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/extractor.py orchestrator/tests/test_extractor.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): add extract_document_sectioned for per-section specs

Selects shared.md + <section>.md per chunk based on its section
label, falling back to default.md for unclassified chunks. Existing
extract_document (single flat spec) is untouched — used by the
general extraction pass.
EOF
)"
```

---

### Task 7: Wire section-stratified extraction into the `research_paper` domain cascade

**Files:**
- Modify: `orchestrator/src/routes/ingest.py`
- Test: `orchestrator/tests/test_ingest_route.py`

**Interfaces:**
- Consumes: `chunk_by_sections(relay, text, model, chunk_size, overlap) -> list[dict]` (Task 3).
- Consumes: `extract_document_sectioned(relay, chunks, section_specs, model) -> list[dict]` (Task 6).
- Produces: `_load_research_paper_specs() -> dict[str, str]` — loads and composes `shared.md + <section>.md` for every file in `orchestrator/specs/research_paper/` except `shared.md` and `default.md`, plus a `"default"` key built from `shared.md + default.md`.

- [ ] **Step 1: Read the current cascade block to understand the exact insertion point**

Before editing, re-read `orchestrator/src/routes/ingest.py`'s "4. Cascade through domain specs" loop (the `for domain_path in domains:` block covered earlier in this conversation) to confirm the current variable names (`domain_spec`, `ancestor`, `seen_specs`, `domain_entity_count`, `chunk_entities`) haven't drifted, since this task edits inside that loop.

- [ ] **Step 2: Write the failing test**

```python
# append to orchestrator/tests/test_ingest_route.py — check the existing file's fixtures
# (client, mock relay patterns) before writing this; reuse them rather than reinventing.
def test_research_paper_domain_uses_section_specs(client, monkeypatch):
    """When a document classifies into the research_paper domain and no simmered
    spec exists yet, extraction should use the built-in per-section spec directory
    rather than a single flat spec string."""
    import src.routes.ingest as ingest_module

    calls = []

    async def fake_extract_document_sectioned(relay, chunks, section_specs, model):
        calls.append(section_specs)
        return []

    async def fake_chunk_by_sections(relay, text, model, chunk_size=2000, overlap=200):
        return [{"id": "c1", "chunk_index": 0, "offset": 0, "length": len(text), "text": text, "section": "introduction"}]

    monkeypatch.setattr(ingest_module, "extract_document_sectioned", fake_extract_document_sectioned)
    monkeypatch.setattr(ingest_module, "chunk_by_sections", fake_chunk_by_sections)
    # Force classification to research_paper — patch classify_document / assign_document_domains
    # per the existing test file's pattern for forcing a domain (read a nearby test that
    # already does this, e.g. one testing domain cascade, and mirror its monkeypatch calls).

    response = client.post("/ingest", files={"file": ("paper.txt", b"## Introduction\nWe propose X.\n", "text/plain")})
    assert response.status_code == 200
    assert len(calls) >= 1
    assert "introduction" in calls[0]
    assert "default" in calls[0]
```

Note: this test's exact monkeypatch-the-classifier mechanics depend on patterns already present in `test_ingest_route.py` (there are 45+ existing orchestrator tests, several already force a specific domain classification for cascade testing) — read that file first and copy its established approach for forcing `research_paper` classification rather than inventing a new one.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd orchestrator && pytest tests/test_ingest_route.py -v -k research_paper_domain_uses_section_specs`
Expected: FAIL (function `extract_document_sectioned`/`chunk_by_sections` not yet referenced in `ingest.py`, or cascade doesn't call them)

- [ ] **Step 4: Add the spec-directory loader to `ingest.py`**

Near the top of `ingest.py`, alongside `_load_general_spec` / `GENERAL_TEXT_SPEC`:

```python
from ..pipeline.chunker import chunk_by_sections
from ..pipeline.extractor import extract_document_sectioned

_RESEARCH_PAPER_SPECS_DIR = _SPECS_DIR / "research_paper"


def _load_research_paper_specs() -> dict[str, str]:
    shared = (_RESEARCH_PAPER_SPECS_DIR / "shared.md").read_text()
    specs = {}
    for path in _RESEARCH_PAPER_SPECS_DIR.glob("*.md"):
        if path.stem == "shared":
            continue
        key = "default" if path.stem == "default" else path.stem
        specs[key] = shared + "\n\n---\n\n" + path.read_text()
    return specs


RESEARCH_PAPER_SPECS = _load_research_paper_specs()
```

- [ ] **Step 5: Use section-stratified extraction in the domain cascade for `research_paper`**

Inside the `for domain_path in domains:` cascade loop, in the branch that currently does:

```python
            if domain_spec and domain_spec.id not in seen_specs:
                seen_specs.add(domain_spec.id)
                d_entities = await extract_document(
                    relay=relay, chunks=chunks,
                    spec=domain_spec.spec_content, model=settings.extraction_model,
                )
```

add a fallback branch for when there's no simmered override AND the ancestor is `research_paper` (mirroring how `GENERAL_TEXT_SPEC` is the fallback when `store.specs.get_general()` returns `None`):

```python
            if domain_spec and domain_spec.id not in seen_specs:
                seen_specs.add(domain_spec.id)
                d_entities = await extract_document(
                    relay=relay, chunks=chunks,
                    spec=domain_spec.spec_content, model=settings.extraction_model,
                )
                for entity in d_entities:
                    entity_id = normalize_entity(store, entity["name"], entity["type"])
                    store.entity_sources.create(
                        entity_id=entity_id, document_id=doc_id, chunk_id=entity.get("chunk_id"),
                        extraction_pass="domain-specific", spec_version=domain_spec.version,
                    )
                    chunk_id = entity.get("chunk_id")
                    if chunk_id:
                        chunk_entities.setdefault(chunk_id, []).append(entity_id)
                domain_entity_count += len(d_entities)
            elif not domain_spec and ancestor == "research_paper" and "research_paper" not in seen_specs:
                seen_specs.add("research_paper")
                sectioned_chunks = await chunk_by_sections(
                    relay=relay, text=content, model=settings.extraction_model,
                    chunk_size=settings.chunk_size,
                )
                for c in sectioned_chunks:
                    c["id"] = str(uuid.uuid4())
                d_entities = await extract_document_sectioned(
                    relay=relay, chunks=sectioned_chunks,
                    section_specs=RESEARCH_PAPER_SPECS, model=settings.extraction_model,
                )
                for entity in d_entities:
                    entity_id = normalize_entity(store, entity["name"], entity["type"])
                    store.entity_sources.create(
                        entity_id=entity_id, document_id=doc_id, chunk_id=entity.get("chunk_id"),
                        extraction_pass="domain-specific", spec_version=0,
                    )
                    chunk_id = entity.get("chunk_id")
                    if chunk_id:
                        chunk_entities.setdefault(chunk_id, []).append(entity_id)
                domain_entity_count += len(d_entities)
```

Note: this re-chunks the document specifically for the section-aware pass rather than reusing the
general-pass `chunks` list, since those chunks don't carry `section` labels — this duplicates one
extra `chunk_by_sections` LLM-fallback cost per research-paper document, which is acceptable per
the design (documents matching this domain are relatively rare and the fallback only fires for
unheaded stretches, not every chunk).

- [ ] **Step 6: Run test to verify it passes**

Run: `cd orchestrator && pytest tests/test_ingest_route.py -v -k research_paper_domain_uses_section_specs`
Expected: PASS

- [ ] **Step 7: Run the full orchestrator test suite to check for regressions**

Run: `cd orchestrator && pytest tests/ -v`
Expected: PASS (all tests, including the pre-existing 45+)

- [ ] **Step 8: Commit**

```bash
git add orchestrator/src/routes/ingest.py orchestrator/tests/test_ingest_route.py
git commit -m "$(cat <<'EOF'
feat(ingest): use section-stratified spec for research_paper domain

Mirrors the existing GENERAL_TEXT_SPEC built-in fallback pattern: when
no simmered override exists yet for the research_paper domain, load
orchestrator/specs/research_paper/*.md and extract with
extract_document_sectioned instead of a single flat spec.
EOF
)"
```

---

### Task 8: Standalone CLI script for section-spec iteration against real PDFs

**Files:**
- Create: `orchestrator/scripts/test_section_spec.py`
- Test: manual validation only (see Step 4) — this is an interactive authoring tool, not covered by pytest per the approved design ("No expected-answer scoring/diffing").

**Interfaces:**
- Consumes: `extract_text_from_pdf(file_bytes) -> str` (existing, `file_extractor.py`).
- Consumes: `label_sections(relay, text, model) -> list[dict]` (Task 2).
- Consumes: `chunk_document(text, chunk_size, overlap) -> list[dict]` (existing).
- Consumes: `extract_entities_from_chunk(relay, chunk_text, spec, model) -> list[dict]` (existing).
- Consumes: `RESEARCH_PAPER_SPECS` composition logic — reimplement `_load_research_paper_specs`'s
  body inline in the script (don't import from `routes.ingest`, since that module has FastAPI/DB
  side-effecting imports at load time not appropriate for a standalone script) by reading
  directly from `orchestrator/specs/research_paper/`.

- [ ] **Step 1: Create the script**

```python
# orchestrator/scripts/test_section_spec.py
# ABOUTME: Standalone CLI to test a research_paper section spec against a real PDF.
# ABOUTME: Prints a raw entity dump per chunk for manual spec iteration — no scoring.

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings
from src.pipeline.chunker import chunk_document
from src.pipeline.extractor import extract_entities_from_chunk
from src.pipeline.file_extractor import extract_text_from_pdf
from src.pipeline.section_splitter import label_sections
from orrery_relay import Relay

_SPECS_DIR = Path(__file__).resolve().parent.parent / "specs" / "research_paper"


def _load_section_spec(section: str) -> str:
    shared = (_SPECS_DIR / "shared.md").read_text()
    section_file = _SPECS_DIR / f"{section}.md"
    if not section_file.exists():
        section_file = _SPECS_DIR / "default.md"
    return shared + "\n\n---\n\n" + section_file.read_text()


async def run(paper_path: str, target_section: str | None) -> None:
    settings = get_settings()
    relay = Relay.from_settings(settings)

    file_bytes = Path(paper_path).read_bytes()
    text = extract_text_from_pdf(file_bytes)

    spans = await label_sections(relay, text, model=settings.extraction_model)
    print(f"Detected {len(spans)} section span(s):")
    for span in spans:
        print(f"  [{span['section']}] chars {span['start']}-{span['end']} ({span['end'] - span['start']} chars)")
    print()

    for span in spans:
        if target_section and span["section"] != target_section:
            continue
        span_text = text[span["start"]:span["end"]]
        spec = _load_section_spec(span["section"])
        chunks = chunk_document(span_text, chunk_size=settings.chunk_size)
        print(f"=== Section: {span['section']} ({len(chunks)} chunk(s)) ===")
        for i, chunk in enumerate(chunks):
            entities = await extract_entities_from_chunk(
                relay=relay, chunk_text=chunk["text"], spec=spec, model=settings.extraction_model,
            )
            print(f"  --- chunk {i} ---")
            for entity in entities:
                print(f"    {entity['type']}: {entity['name']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test a research_paper section spec against a real PDF")
    parser.add_argument("--paper", required=True, help="Path to a PDF file, e.g. pi0/papers/kimOpenVLA2024.pdf")
    parser.add_argument("--section", help="Only test this section (introduction, method, etc.)")
    parser.add_argument("--all-sections", action="store_true", help="Test every detected section")
    args = parser.parse_args()

    if not args.section and not args.all_sections:
        parser.error("Pass --section <name> or --all-sections")

    asyncio.run(run(args.paper, args.section))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Confirm the script's import path works standalone**

Run: `cd orchestrator && python scripts/test_section_spec.py --help`
Expected: argparse help text prints with no import errors (verifies `sys.path` insertion and all module imports resolve without needing `pip install -e .` to have registered `orchestrator` as a package — if it fails on `orrery_relay` or `src.config`, check whether the project is already installed in editable mode per the "Without Docker (native dev)" section of `CLAUDE.md`, and note that requirement in the script's own docstring instead of trying to work around it).

- [ ] **Step 3: Run it against a real PDF and eyeball the output**

Requires a working `.env` / backend configuration per `CLAUDE.md`'s "Starting the Services" section (any of `gateway`/`bedrock`/`ollama`).

```bash
cd orchestrator && python scripts/test_section_spec.py --paper ../pi0/papers/kimOpenVLA2024.pdf --all-sections
```

Expected: prints detected section spans (character ranges) followed by a per-chunk entity dump for each section. Confirm:
- Section boundaries look plausible for this paper (spot-check against the actual PDF structure).
- Introduction chunks don't yield vague-capability `task` entities.
- Experiments/Results chunks yield a comparably dense set of `model`/`task` entities (recall-favoring).

Use this run — and repeat runs against `wangCLASH2026.pdf`, `linVILA2024.pdf`, etc. — to manually tune the section `.md` files from Task 5 if the output looks off. This tuning loop is the deliverable; there is no further automated step.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/scripts/test_section_spec.py
git commit -m "$(cat <<'EOF'
feat(scripts): add standalone CLI to test research_paper section specs

Runs the real PDF extraction path (extract_text_from_pdf) against
pi0/papers/*.pdf, splits into sections, and prints a raw per-chunk
entity dump for manually iterating on each section's .md spec file.
No automated scoring, by design — see the approved design doc.
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** section detection (Task 1-2), section-aware chunking (Task 3), DB schema for
  persisting section labels (Task 4), the actual per-section spec content (Task 5), section-aware
  extraction (Task 6), cascade wiring (Task 7), and the CLI testing tool (Task 8) — all five design
  sections have a corresponding task.
- **Placeholder scan:** no TBD/TODO; every code step has real code, not descriptions.
- **Type consistency:** `chunk["section"]` key name is consistent from `chunk_by_sections` (Task
  3) through `extract_document_sectioned` (Task 6) through `ingest.py` wiring (Task 7). `Chunk`
  dataclass's `section` field (Task 4) matches the DB column name (`section`) and the dict key
  used pre-persistence.
- **Known risk flagged inline:** Task 7 re-chunks the document for the section-aware pass rather
  than threading section labels through the general-pass `chunks` list — called out explicitly in
  Step 5's note rather than silently doubling chunking cost without explanation.
