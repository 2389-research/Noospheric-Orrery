# Obsidian Vault Import (#41) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the naive `.md`-walk vault featurizer into a real Obsidian importer — skipping vault junk, keeping frontmatter and wikilink/comment syntax out of extracted entities, and carrying frontmatter through as provenance metadata — so pointing Orrery at a real vault yields clean documents with no `.obsidian`/`.trash` noise.

**Architecture:** All changes are contained in the **worker's vault featurizer** plus two small, additive touches to the shared sync spine. A featurizer stops yielding a positional 4-tuple and instead yields an extensible `SourceDoc` record; a new shared `ignore` policy (mirroring `orrery-codesum`'s `fileselect`) prunes junk directories during an `os.walk`; new pure `markdown` helpers split frontmatter and clean wikilinks/comments out of the body before extraction; and `upsert_document` gains a `metadata` param that writes to the **already-existing** `documents.metadata` column (no schema migration). Frontmatter/folder → domain hints are an opt-in final tier.

**Tech Stack:** Python 3.12, SQLite (WAL), pytest/pytest-asyncio, PyYAML (new worker dep). Featurizer contract lives in `worker/src/featurizers/`; sync spine in `worker/src/jobs/`.

---

## Context the executor needs

**Read first:**
- GitHub issue #41 (the spec for this work) and #42 (continuous hot-folder watching — *out of scope here*, its plumbing already exists and is what this featurizer feeds).
- `docs/superpowers/specs/2026-08-14-incremental-source-sync-design.md` — the sync spine this featurizer plugs into (the "invariant core / pluggable featurizer" seam, §10–§11).
- `CLAUDE.md` → **Testing** section. **Worker tests run inside the worker container, via `uv run`, not natively** (native runs segfault on torch/sentence-transformers). The pure-function modules added here (`ignore.py`, `markdown.py`, `base.py`) import nothing heavy, but run the suite in Docker to match CI-adjacent reality. Commands are repeated in each task.

**Ground-truth facts already verified (do not re-litigate):**
- `documents.metadata TEXT` **exists in both schema mirrors** (`orchestrator/src/db.py:21`, `worker/src/db.py:14`) → **no migration, no `test_schema_mirror` change.**
- PyYAML is **not** a worker dependency yet (`worker/pyproject.toml`) → this plan adds it.
- The featurizer contract is a positional 4-tuple `(source_path, title, content, emits_cooccurrence)`, unpacked at `worker/src/jobs/scan_source.py:78`.
- `upsert_document` (`worker/src/jobs/upsert_document.py:173`) already imports `json`, already accepts `domain_path`/`classify`, and does **not** write `metadata` today (INSERT at :231, UPDATE at :221).
- Prior art for the ignore policy: `packages/orrery-codesum/src/orrery_codesum/fileselect.py` (skip-any-dotfolder rule + curated sets) and `packages/orrery-codesum/src/orrery_codesum/traverse.py` (os.walk with `dirnames[:]` pruning).

## File Structure

**Create:**
- `worker/src/featurizers/base.py` — the `SourceDoc` record (extensible featurizer output contract). One responsibility: the featurizer→spine data shape.
- `worker/src/featurizers/ignore.py` — shared path-ignore policy (defaults + `config["ignore"]` override). One responsibility: "should this dir/file be skipped."
- `worker/src/featurizers/markdown.py` — pure Obsidian-markdown helpers: `parse_frontmatter`, `clean_markdown`. One responsibility: text-shape transforms, no I/O.
- Tests: `worker/tests/test_featurizer_ignore.py`, `worker/tests/test_featurizer_markdown.py`, `worker/tests/test_vault_featurizer.py`, `worker/tests/test_upsert_metadata.py`.

**Modify:**
- `worker/src/featurizers/vault.py` — walk via `os.walk`+pruning; parse+clean each note; yield `SourceDoc`.
- `worker/src/jobs/scan_source.py` — consume `SourceDoc` (via a tolerant coercion) instead of unpacking a 4-tuple; thread `metadata`/`domain_hint` into `upsert_document`.
- `worker/src/jobs/upsert_document.py` — add `metadata=None` param; write it on INSERT and UPDATE.
- `worker/pyproject.toml` — add `pyyaml` dependency.

**Out of scope (note as known limitations / separate issues, do NOT build here):**
- Wikilinks as first-class document→document graph edges (needs a doc-edge schema home; file as its own issue).
- The `upsert_document` "restore a soft-deleted doc at the same source_path" bug (CodeRabbit #78 finding; its own fix).
- `source_path` relativization and rename/move detection (spine identity decisions; note as limitations).
- Attachments (PDF/image) ingestion — the ignore policy deliberately skips them (text-only MVP, per #41's open question).

---

### Task 1: Extensible featurizer record (`SourceDoc`)

Replace the positional 4-tuple contract so later tasks can add fields without breaking every unpack site.

**Files:**
- Create: `worker/src/featurizers/base.py`
- Modify: `worker/src/jobs/scan_source.py:78`
- Test: `worker/tests/test_featurizer_markdown.py` (temporary home for the coercion test; or a small `test_source_doc.py`)

- [ ] **Step 1: Write the failing test**

Create `worker/tests/test_source_doc.py`:

```python
from src.featurizers.base import SourceDoc


def test_coerce_passthrough():
    d = SourceDoc(source_path="/v/a.md", title="a", content="body")
    assert SourceDoc.coerce(d) is d
    assert d.emits_cooccurrence is True
    assert d.metadata is None and d.domain_hint is None


def test_coerce_legacy_4_tuple():
    d = SourceDoc.coerce(("/v/a.md", "a", "body", False))
    assert (d.source_path, d.title, d.content, d.emits_cooccurrence) == ("/v/a.md", "a", "body", False)


def test_coerce_legacy_3_tuple_defaults_emit_true():
    d = SourceDoc.coerce(("/v/a.md", "a", "body"))
    assert d.emits_cooccurrence is True
```

- [ ] **Step 2: Run test to verify it fails**

Run (in the worker container — see CLAUDE.md Testing):
```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest --with pytest-asyncio \
  python -m pytest tests/test_source_doc.py -q
```
Expected: FAIL — `No module named src.featurizers.base`.

- [ ] **Step 3: Write minimal implementation**

Create `worker/src/featurizers/base.py`:

```python
# ABOUTME: SourceDoc — the extensible output contract a featurizer yields to the sync spine.
# ABOUTME: Replaces the positional 4-tuple so new fields (metadata, hints) are additive.
"""One record per document a source produces.

A featurizer yields SourceDoc instances; scan_source coerces + upserts each. Legacy
featurizers/fixtures that still yield a 3- or 4-tuple are accepted via SourceDoc.coerce,
so adding fields never breaks an unpack site.
"""
from dataclasses import dataclass


@dataclass
class SourceDoc:
    source_path: str
    title: str
    content: str
    emits_cooccurrence: bool = True
    metadata: dict | None = None      # provenance (e.g. parsed frontmatter); JSON-stored on the doc
    domain_hint: str | None = None    # if set, used as the doc's domain (skips LLM classification)

    @classmethod
    def coerce(cls, item):
        """Accept a SourceDoc or a legacy (path, title, content[, emits]) tuple."""
        if isinstance(item, cls):
            return item
        source_path, title, content, *rest = item
        emits = rest[0] if rest else True
        return cls(source_path=source_path, title=title, content=content,
                   emits_cooccurrence=emits)
```

- [ ] **Step 4: Modify `scan_source._sync_via_featurizer` to consume records**

In `worker/src/jobs/scan_source.py`, add the import near the top:
```python
from ..featurizers.base import SourceDoc
```
Replace the loop body at `:78` (currently `for source_path, title, content, emits in featurizer(...)`):
```python
    for item in featurizer(ws["uri"], source_config):
        doc = SourceDoc.coerce(item)
        seen_paths.add(doc.source_path)
        res = await upsert_document(
            conn, relay, settings, source_path=doc.source_path, title=doc.title,
            content=doc.content, source_id=source_id,
            emits_cooccurrence=doc.emits_cooccurrence,
            metadata=doc.metadata, domain_path=doc.domain_hint)
        actions[res["action"]] = actions.get(res["action"], 0) + 1
```
(`metadata=` lands in Task 5; `domain_path=doc.domain_hint` is already a valid param — `None` preserves today's classify behavior.)

- [ ] **Step 5: Run tests to verify pass (and nothing regressed)**

```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest --with pytest-asyncio \
  python -m pytest tests/test_source_doc.py tests/test_scan_source.py -q
```
Expected: PASS. (If `test_scan_source.py` injects tuple-yielding fixtures via `_FEATURIZERS`, `coerce` keeps them working — that is the point.)

- [ ] **Step 6: Commit**

```bash
git add worker/src/featurizers/base.py worker/src/jobs/scan_source.py worker/tests/test_source_doc.py
git commit -m "refactor(featurizers): SourceDoc record replaces the positional tuple contract"
```

---

### Task 2: Shared ignore policy + prune the vault walk

Give fs-walking featurizers a gitignore-equivalent: per-type defaults (dotfolders → `.obsidian`/`.trash` free, binaries, caches) plus a `config["ignore"]` override. Wire it into the vault walk via `os.walk` pruning.

**Files:**
- Create: `worker/src/featurizers/ignore.py`
- Modify: `worker/src/featurizers/vault.py`
- Test: `worker/tests/test_featurizer_ignore.py`

- [ ] **Step 1: Write the failing test**

Create `worker/tests/test_featurizer_ignore.py`:

```python
from src.featurizers.ignore import should_skip_dir, should_skip_file


def test_dotfolders_skipped_by_default():
    assert should_skip_dir(".obsidian")
    assert should_skip_dir(".trash")
    assert should_skip_dir(".git")


def test_content_dir_not_skipped():
    assert not should_skip_dir("Projects")


def test_binary_and_cache_files_skipped():
    assert should_skip_file("diagram.PNG")   # case-folded
    assert should_skip_file("notes.pdf")
    assert not should_skip_file("note.md")


def test_config_extra_dirs_skipped():
    assert should_skip_dir("Templates", extra_dirs={"Templates"})
    assert not should_skip_dir("Templates")
```

- [ ] **Step 2: Run to verify it fails**

```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest python -m pytest tests/test_featurizer_ignore.py -q
```
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

Create `worker/src/featurizers/ignore.py`:

```python
# ABOUTME: Shared path-ignore policy for filesystem-walking featurizers (vault, hot folder).
# ABOUTME: Defaults mirror orrery-codesum's fileselect; per-source config["ignore"] extends them.
"""A gitignore-equivalent for ingestion.

Defaults skip any dotfolder (so `.obsidian/` and `.trash/` never ingest), common caches,
and binary/attachment suffixes (text-only MVP). A source's config may extend the skipped
directory names via `config["ignore"]`.
"""
import os

DEFAULT_SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", "__pycache__"}
DEFAULT_SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".mp3", ".mp4", ".mov",
}


def should_skip_dir(name: str, extra_dirs=()) -> bool:
    """Skip any dotfolder, the curated defaults, and any name the source configured."""
    return name.startswith(".") or name in DEFAULT_SKIP_DIRS or name in set(extra_dirs)


def should_skip_file(name: str, extra_suffixes=()) -> bool:
    """Skip binaries/attachments by suffix (case-folded)."""
    _, ext = os.path.splitext(name)
    return ext.lower() in (DEFAULT_SKIP_SUFFIXES | set(extra_suffixes))
```

- [ ] **Step 4: Run to verify pass**

```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest python -m pytest tests/test_featurizer_ignore.py -q
```
Expected: PASS.

- [ ] **Step 5: Rewrite the vault walk to prune with `os.walk`**

In `worker/src/featurizers/vault.py`, replace the `rglob` walk. `rglob` cannot prune a subtree, so it still stats every file under `.obsidian/`. Use `os.walk` and mutate `dirnames` in place (same technique as `orrery-codesum/traverse.py`). Interim `enumerate_vault` (frontmatter/cleaning arrive in Tasks 3–4):

```python
# ABOUTME: Vault featurizer — an Obsidian-style note dir -> one SourceDoc per note.
# ABOUTME: Prunes junk dirs (.obsidian/.trash), then parses+cleans each markdown note.
"""source -> iterator[SourceDoc]. The vault adapter for the incremental-source-sync spine."""
import os
from pathlib import Path

from .base import SourceDoc
from .ignore import should_skip_dir, should_skip_file


def _iter_note_paths(root: Path, exts: set, extra_dirs):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not should_skip_dir(d, extra_dirs))
        for fn in sorted(filenames):
            if Path(fn).suffix.lower() in exts and not should_skip_file(fn):
                yield Path(dirpath) / fn


def enumerate_vault(uri: str, config: dict):
    config = config or {}
    exts = {("." + str(e).lstrip(".")).lower() for e in (config.get("ext") or [".md"])}
    extra_dirs = config.get("ignore") or []
    root = Path(uri)
    if not root.exists():
        return
    for f in _iter_note_paths(root, exts, extra_dirs):
        text = f.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        yield SourceDoc(source_path=str(f), title=f.stem, content=text,
                        emits_cooccurrence=True)
```

- [ ] **Step 6: Commit**

```bash
git add worker/src/featurizers/ignore.py worker/src/featurizers/vault.py worker/tests/test_featurizer_ignore.py
git commit -m "feat(vault): shared ignore policy + os.walk pruning (skips .obsidian/.trash)"
```

---

### Task 3: Frontmatter parsing (add PyYAML)

Split the leading `---` YAML block off the body so it never reaches extraction, and return it as a dict for provenance/hints.

**Files:**
- Modify: `worker/pyproject.toml` (add `pyyaml`)
- Create: `worker/src/featurizers/markdown.py`
- Modify: `worker/src/featurizers/vault.py`
- Test: `worker/tests/test_featurizer_markdown.py`

- [ ] **Step 1: Add the dependency**

In `worker/pyproject.toml`, add to `dependencies`:
```toml
    "pyyaml>=6.0",
```
Then rebuild the worker image so the dep is present before running tests:
```bash
docker-compose build worker && docker-compose up -d --no-deps worker
```
(Check `/stats` shows `active_jobs == 0` before recreating — see CLAUDE.md.)

- [ ] **Step 2: Write the failing test**

Create `worker/tests/test_featurizer_markdown.py`:

```python
from src.featurizers.markdown import parse_frontmatter


def test_parse_frontmatter_splits_block_and_body():
    text = "---\ntitle: Q3\ntags: [project, roadmap]\n---\n# Q3\nThe body.\n"
    meta, body = parse_frontmatter(text)
    assert meta["title"] == "Q3"
    assert meta["tags"] == ["project", "roadmap"]
    assert body.lstrip().startswith("# Q3")
    assert "tags:" not in body   # frontmatter must not leak into the body


def test_parse_frontmatter_absent():
    meta, body = parse_frontmatter("# Just a note\nno frontmatter\n")
    assert meta == {}
    assert body.startswith("# Just a note")


def test_parse_frontmatter_malformed_yaml_is_safe():
    text = "---\n: : broken\n---\nbody\n"
    meta, body = parse_frontmatter(text)
    assert meta == {}          # never raise on bad YAML
    assert body.strip() == "body"
```

- [ ] **Step 3: Run to verify it fails**

```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest python -m pytest tests/test_featurizer_markdown.py -q
```
Expected: FAIL — module missing.

- [ ] **Step 4: Write minimal implementation**

Create `worker/src/featurizers/markdown.py`:

```python
# ABOUTME: Pure Obsidian-markdown helpers — frontmatter split + wikilink/comment cleaning.
# ABOUTME: No I/O; safe on malformed input (never raises).
import re

import yaml

_FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def parse_frontmatter(text: str):
    """Return (metadata_dict, body). No frontmatter -> ({}, text). Bad YAML -> ({}, body)."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        meta = None
    if not isinstance(meta, dict):
        meta = {}
    return meta, text[m.end():]
```

- [ ] **Step 5: Wire into `enumerate_vault`**

In `worker/src/featurizers/vault.py`, import and use it:
```python
from .markdown import parse_frontmatter
```
In the loop, replace the `SourceDoc(...)` yield:
```python
        meta, body = parse_frontmatter(text)
        if not body.strip():
            continue
        title = (meta.get("title") if isinstance(meta.get("title"), str) else None) or f.stem
        yield SourceDoc(source_path=str(f), title=title, content=body,
                        emits_cooccurrence=True, metadata=(meta or None))
```
(Note: the `if not text.strip()` guard moves to `if not body.strip()`.)

- [ ] **Step 6: Run to verify pass**

```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest python -m pytest tests/test_featurizer_markdown.py -q
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add worker/pyproject.toml worker/src/featurizers/markdown.py worker/src/featurizers/vault.py worker/tests/test_featurizer_markdown.py
git commit -m "feat(vault): parse+strip YAML frontmatter (adds pyyaml)"
```

---

### Task 4: Clean wikilinks, embeds, and comments

Strip Obsidian syntax so the extractor sees clean prose: `[[a|b]]→b`, `[[a#h]]→a`, `[[a]]→a`, drop `![[embed]]` and `%%comments%%`.

**Files:**
- Modify: `worker/src/featurizers/markdown.py`
- Modify: `worker/src/featurizers/vault.py`
- Test: `worker/tests/test_featurizer_markdown.py`

- [ ] **Step 1: Write the failing test** (append to `test_featurizer_markdown.py`)

```python
from src.featurizers.markdown import clean_markdown


def test_clean_wikilinks():
    assert clean_markdown("see [[Q3 Planning]] and [[Note|the note]]") == \
        "see Q3 Planning and the note"


def test_clean_wikilink_with_heading_anchor():
    assert clean_markdown("[[Note#Section]] ref") == "Note ref"


def test_drop_embeds_and_comments():
    assert "image.png" not in clean_markdown("![[image.png]]")
    assert clean_markdown("visible %%hidden note%% text") == "visible  text"
```

- [ ] **Step 2: Run to verify it fails**

```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest python -m pytest tests/test_featurizer_markdown.py -q
```
Expected: FAIL — `clean_markdown` undefined.

- [ ] **Step 3: Write minimal implementation** (add to `markdown.py`)

```python
_COMMENT_RE = re.compile(r"%%.*?%%", re.DOTALL)
_EMBED_RE = re.compile(r"!\[\[[^\]]*\]\]")          # image/note embeds -> dropped
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")       # [[target(#heading)?(|display)?]]


def _wikilink_text(m: "re.Match") -> str:
    inner = m.group(1)
    if "|" in inner:                # [[target|display]] -> display
        return inner.split("|", 1)[1]
    return inner.split("#", 1)[0]   # [[target#heading]] -> target


def clean_markdown(text: str) -> str:
    """Strip Obsidian comments/embeds and reduce wikilinks to their visible text."""
    text = _COMMENT_RE.sub("", text)
    text = _EMBED_RE.sub("", text)          # must run before the wikilink sub
    return _WIKILINK_RE.sub(_wikilink_text, text)
```

- [ ] **Step 4: Wire into `enumerate_vault`**

In `vault.py`, import `clean_markdown` and apply it to the body after frontmatter split:
```python
from .markdown import parse_frontmatter, clean_markdown
```
```python
        meta, body = parse_frontmatter(text)
        body = clean_markdown(body)
        if not body.strip():
            continue
```

- [ ] **Step 5: Run to verify pass**

```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest python -m pytest tests/test_featurizer_markdown.py -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add worker/src/featurizers/markdown.py worker/src/featurizers/vault.py worker/tests/test_featurizer_markdown.py
git commit -m "feat(vault): clean wikilinks, embeds, and comments before extraction"
```

---

### Task 5: Persist `metadata` in `upsert_document`

Write the parsed frontmatter into the existing `documents.metadata` column so provenance travels with the doc (this is also the #79 provenance groundwork).

**Files:**
- Modify: `worker/src/jobs/upsert_document.py` (INSERT :231, UPDATE :221, signature :173)
- Test: `worker/tests/test_upsert_metadata.py`

- [ ] **Step 1: Write the failing test**

Create `worker/tests/test_upsert_metadata.py`. Follow the fixture style of the existing `worker/tests/test_upsert_document.py` (a `tmp_path` file DB + a fake relay). Minimal shape:

```python
import json
import pytest
from src.db import init_db, get_connection
from src.jobs.upsert_document import upsert_document
# reuse whatever fake-relay + settings helpers test_upsert_document.py already defines


@pytest.mark.asyncio
async def test_metadata_persisted_on_create(tmp_path, fake_relay, settings):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    await upsert_document(conn, fake_relay, settings, source_path="/v/a.md",
                          title="a", content="body", classify=False,
                          metadata={"tags": ["x"], "title": "a"})
    row = conn.execute("SELECT metadata FROM documents WHERE source_path='/v/a.md'").fetchone()
    assert json.loads(row["metadata"])["tags"] == ["x"]


@pytest.mark.asyncio
async def test_metadata_updated_in_place(tmp_path, fake_relay, settings):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    await upsert_document(conn, fake_relay, settings, source_path="/v/a.md",
                          title="a", content="v1", classify=False, metadata={"v": 1})
    await upsert_document(conn, fake_relay, settings, source_path="/v/a.md",
                          title="a", content="v2", classify=False, metadata={"v": 2})
    row = conn.execute("SELECT metadata FROM documents WHERE source_path='/v/a.md'").fetchone()
    assert json.loads(row["metadata"])["v"] == 2
```

If `test_upsert_document.py` does not expose reusable `fake_relay`/`settings` fixtures, promote them to `worker/tests/conftest.py` first (own commit) so both test modules share them — DRY.

- [ ] **Step 2: Run to verify it fails**

```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest --with pytest-asyncio python -m pytest tests/test_upsert_metadata.py -q
```
Expected: FAIL — `upsert_document() got an unexpected keyword argument 'metadata'`.

- [ ] **Step 3: Implement**

In `worker/src/jobs/upsert_document.py`:

Add `metadata=None` to the signature (`:173`), e.g. after `content_type="text",`:
```python
                          content_type="text", metadata=None, domain_path=None,
```

Add a serialization helper near the top-of-function body (`json` is already imported):
```python
    meta_json = json.dumps(metadata, default=str) if metadata else None
```
(`default=str` guards against frontmatter dates, which are not JSON-serializable.)

UPDATE branch (`:221`) — add `metadata = ?`:
```python
        conn.execute(
            "UPDATE documents SET title = ?, content = ?, content_hash = ?, content_type = ?, "
            "metadata = ?, modified_at = CURRENT_TIMESTAMP, source_id = COALESCE(source_id, ?), "
            "status = 'pending' WHERE id = ?",
            (title, content, chash, content_type, meta_json, source_id, doc_id))
```

INSERT branch (`:231`) — add the `metadata` column + value:
```python
        conn.execute(
            "INSERT INTO documents (id, title, content, content_hash, source_path, source_id, "
            "content_type, metadata, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (doc_id, title, content, chash, source_path, source_id, content_type, meta_json))
```

- [ ] **Step 4: Run to verify pass (+ no regression)**

```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest --with pytest-asyncio \
  python -m pytest tests/test_upsert_metadata.py tests/test_upsert_document.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add worker/src/jobs/upsert_document.py worker/tests/test_upsert_metadata.py worker/tests/conftest.py
git commit -m "feat(sync): persist document metadata (frontmatter) in upsert_document"
```

---

### Task 6 (opt-in): Frontmatter tags + folder → domain hint

Turn a vault's own structure into classification signal. **Opt-in** via `config["folder_domains"]` so the default path keeps today's LLM classification. Providing a `domain_hint` makes `upsert_document` use it directly and **skip** the classifier (cheaper, deterministic).

**Files:**
- Modify: `worker/src/featurizers/vault.py`
- Test: `worker/tests/test_vault_featurizer.py`

- [ ] **Step 1: Write the failing test** (part of the Task 7 file; add now)

```python
from pathlib import Path
from src.featurizers.vault import enumerate_vault


def test_folder_becomes_domain_hint_when_enabled(tmp_path):
    (tmp_path / "Projects" / "Orrery").mkdir(parents=True)
    (tmp_path / "Projects" / "Orrery" / "note.md").write_text("body text", encoding="utf-8")
    docs = list(enumerate_vault(str(tmp_path), {"folder_domains": True}))
    assert docs[0].domain_hint == "projects/orrery"


def test_no_domain_hint_by_default(tmp_path):
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "note.md").write_text("body", encoding="utf-8")
    docs = list(enumerate_vault(str(tmp_path), {}))
    assert docs[0].domain_hint is None
```

- [ ] **Step 2: Run to verify it fails**, then implement in `vault.py`:

```python
def _folder_domain(path: Path, root: Path) -> str | None:
    rel = path.parent.relative_to(root)
    parts = [p for p in rel.parts if p]     # note at vault root -> no folder domain
    return "/".join(p.lower() for p in parts) if parts else None
```
In the loop, when enabled:
```python
        domain_hint = None
        if config.get("folder_domains"):
            domain_hint = _folder_domain(f, root)
        yield SourceDoc(..., metadata=(meta or None), domain_hint=domain_hint)
```
Domain-path format is a lowercase `/`-separated hierarchical key (see CLAUDE.md "Domain path format").

- [ ] **Step 3: Run to verify pass; Step 4: Commit**

```bash
git add worker/src/featurizers/vault.py worker/tests/test_vault_featurizer.py
git commit -m "feat(vault): opt-in folder->domain hint (config.folder_domains)"
```

> **Decision to surface to the human:** whether `folder_domains` should default **on** (vault folders are a hand-made taxonomy — high value, but silently skips LLM classification) or stay **opt-in** as written. Left opt-in here to avoid surprising existing vault imports. `tags`→domain mapping is intentionally deferred (tag vocab is noisier than folders); revisit under #50/#79.

---

### Task 7: End-to-end vault fixture test

One test that walks a realistic fixture vault and asserts the whole acceptance criteria of #41 at once.

**Files:**
- Test: `worker/tests/test_vault_featurizer.py`

- [ ] **Step 1: Write the test**

```python
from pathlib import Path
from src.featurizers.vault import enumerate_vault


def _make_vault(root: Path):
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (root / ".trash").mkdir()
    (root / ".trash" / "deleted.md").write_text("I was deleted", encoding="utf-8")
    (root / "note.md").write_text(
        "---\ntitle: Real Note\ntags: [a]\n---\n"
        "Body mentions [[Other Note]] and %%a secret%% here.\n", encoding="utf-8")
    (root / "attach.png").write_bytes(b"\x89PNG\r\n")


def test_vault_import_acceptance(tmp_path):
    _make_vault(tmp_path)
    docs = list(enumerate_vault(str(tmp_path), {}))

    paths = [Path(d.source_path).name for d in docs]
    assert paths == ["note.md"]                       # no .obsidian/.trash/.png junk
    doc = docs[0]
    assert doc.title == "Real Note"                   # frontmatter title wins over stem
    assert "tags:" not in doc.content                 # frontmatter stripped
    assert "%%" not in doc.content                    # comment stripped
    assert "[[" not in doc.content and "Other Note" in doc.content  # wikilink cleaned
    assert doc.metadata["tags"] == ["a"]              # provenance carried
```

- [ ] **Step 2: Run to verify pass**

```bash
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest python -m pytest tests/test_vault_featurizer.py -q
```
Expected: PASS. This is the executable statement of #41's acceptance.

- [ ] **Step 3: Run the full worker suite (guard against regressions)**

```bash
docker exec noospheric-github-worker-1 rm -rf /app/worker/tests
docker cp worker/tests noospheric-github-worker-1:/app/worker/tests
docker exec -w /app/worker -e AWS_ACCESS_KEY=ci -e AWS_SECRET_KEY=ci -e AWS_REGION=us-east-1 \
  noospheric-github-worker-1 uv run --with pytest --with pytest-asyncio \
  python -m pytest tests/ -q --ignore=tests/test_judge_matrix.py
```
Expected: all green (the pre-existing `test_judge_matrix.py` needs a script the image lacks — ignore it, per CLAUDE.md).

- [ ] **Step 4: Commit**

```bash
git add worker/tests/test_vault_featurizer.py
git commit -m "test(vault): end-to-end #41 acceptance fixture"
```

---

### Task 8: Docs + known-limitations note

**Files:**
- Modify: `packages/orrery-*` README or `docs/` ingestion notes as appropriate; at minimum add a short "Vault import" note near the ingestion docs.
- Modify: GitHub issues #41 (close with a summary), and file two follow-ups.

- [ ] **Step 1: Document the vault config surface** — `ext`, `ignore` (extra dir names), `folder_domains` — wherever watched-source registration is documented (`orchestrator/src/routes/watched_sources.py` docstring or the ingestion doc).

- [ ] **Step 2: Record known limitations** (in the same doc):
  - Renaming a note changes `source_path` → treated as delete + create (no move detection).
  - `source_path` is the mounted absolute path → remounting the vault elsewhere re-ingests everything. Relativization is a spine decision, tracked separately.
  - Attachments (PDF/image) are intentionally skipped (text-only).

- [ ] **Step 3: File follow-up issues** (do not implement here):
  - "Obsidian wikilinks as first-class document→document graph edges" (needs a doc-edge schema home; relates to #50/#79).
  - "upsert_document: restore a soft-deleted doc on re-ingest at the same source_path" (CodeRabbit #78 finding).

- [ ] **Step 4: Commit + open the PR**

```bash
git add -A && git commit -m "docs(vault): config surface + known limitations for #41"
git push -u origin plan/obsidian-vault-import-41   # NOTE: do not open/merge a PR without explicit human go-ahead
```

---

## Definition of done
- `test_vault_featurizer.py::test_vault_import_acceptance` passes (the #41 acceptance).
- Full worker suite green (minus the pre-existing `test_judge_matrix.py` ignore).
- No schema migration was needed or made; `test_schema_mirror` untouched and passing.
- #41 closeable; the two follow-up issues filed; the rename/`source_path` limitations recorded.
