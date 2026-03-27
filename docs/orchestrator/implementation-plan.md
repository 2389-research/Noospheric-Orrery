# Orchestrator Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI orchestrator + simmer worker + Next.js dashboard that wires together the validated Noospheric Orrery extraction pipeline into a running service via Docker Compose.

**Architecture:** Three Docker containers (orchestrator API, simmer worker, Next.js frontend) sharing a SQLite database via volume mount. The orchestrator handles ingest/classify/extract synchronously. The simmer worker polls a jobs table and runs simmer-sdk refinement loops asynchronously. The frontend is an admin dashboard for uploading docs, viewing pipeline status, and browsing extracted entities.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (WAL mode), anthropic SDK, simmer-sdk, sentence-transformers (all-MiniLM-L6-v2), Next.js 16, React 19, shadcn/ui, Tailwind 4, Docker Compose.

**Spec:** `docs/orchestrator/design.md`

---

## File Structure

```
noospheric-orrery/
├── docker-compose.yml
├── .env.example
│
├── orchestrator/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI app + lifespan
│   │   ├── config.py                  # Settings from env vars
│   │   ├── db.py                      # SQLite connection + WAL + schema init
│   │   ├── models.py                  # Pydantic models for API request/response
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── ingest.py              # POST /ingest, POST /ingest/directory
│   │   │   ├── documents.py           # GET /documents, GET /documents/{id}
│   │   │   ├── domains.py             # GET /domains
│   │   │   ├── entities.py            # GET /entities, GET /entities/{id}
│   │   │   ├── jobs.py                # GET /jobs
│   │   │   ├── simmer.py              # POST /simmer/general, POST /simmer/{domain}
│   │   │   └── stats.py               # GET /stats
│   │   └── pipeline/
│   │       ├── __init__.py
│   │       ├── chunker.py             # Document chunking logic
│   │       ├── classifier.py          # Sonnet domain classification
│   │       ├── excerpt.py             # Classification excerpt builder
│   │       ├── extractor.py           # Haiku entity extraction with spec
│   │       ├── normalizer.py          # Entity normalization (merge_map + embed)
│   │       ├── domain_normalizer.py   # Domain normalization cascade
│   │       └── cooccurrence.py        # Co-occurrence edge computation
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py                # Shared fixtures (test DB, sample docs)
│       ├── test_db.py
│       ├── test_chunker.py
│       ├── test_excerpt.py
│       ├── test_classifier.py
│       ├── test_extractor.py
│       ├── test_normalizer.py
│       ├── test_domain_normalizer.py
│       ├── test_cooccurrence.py
│       ├── test_ingest_route.py
│       └── test_read_routes.py
│
├── worker/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py                    # Worker entry point (poll loop)
│   │   ├── config.py                  # Shared config (same env vars)
│   │   ├── db.py                      # Same DB module as orchestrator
│   │   ├── jobs/
│   │   │   ├── __init__.py
│   │   │   ├── runner.py              # Job dispatcher (pick job, run handler)
│   │   │   ├── simmer_general.py      # General spec simmering job
│   │   │   ├── simmer_domain.py       # Domain-specific simmering job
│   │   │   └── extract_batch.py       # Batch extraction job
│   │   └── evaluators/
│   │       ├── score_golden_set.py    # Golden set quality scorer
│   │       ├── eval_runner_haiku.py   # Runs extraction spec against docs
│   │       └── eval_scorer.py         # Fuzzy match against golden set
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_runner.py
│       ├── test_simmer_general.py
│       └── test_extract_batch.py
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx             # Root layout with nav
│   │   │   ├── page.tsx               # Upload page (/)
│   │   │   ├── pipeline/
│   │   │   │   └── page.tsx           # Pipeline page
│   │   │   └── entities/
│   │   │       └── page.tsx           # Entities page
│   │   ├── components/
│   │   │   ├── file-upload.tsx        # Drag-and-drop upload zone
│   │   │   ├── upload-status.tsx      # Per-file processing status
│   │   │   ├── stats-bar.tsx          # Dashboard stats summary
│   │   │   ├── domain-tree.tsx        # Domain taxonomy tree/table
│   │   │   ├── jobs-table.tsx         # Pipeline jobs list
│   │   │   └── entity-table.tsx       # Paginated entity table
│   │   └── lib/
│   │       ├── api.ts                 # Typed fetch wrappers for orchestrator API
│   │       └── types.ts               # Shared TypeScript types
│   └── components.json                # shadcn/ui config
│
└── data/                              # Volume mount (created by compose)
    ├── orrery.db
    ├── documents/
    └── specs/
```

**Note on shared code:** The orchestrator and worker share `db.py` and `config.py` logic. Rather than a shared package, both containers copy the same source files. At this scale, duplication is simpler than a monorepo package setup. If this becomes painful, extract a `shared/` package later.

---

## Task 1: Project Scaffolding + Docker Compose

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `orchestrator/Dockerfile`
- Create: `orchestrator/pyproject.toml`
- Create: `orchestrator/src/__init__.py`
- Create: `orchestrator/src/main.py`
- Create: `orchestrator/src/config.py`
- Create: `worker/Dockerfile`
- Create: `worker/pyproject.toml`
- Create: `worker/src/__init__.py`
- Create: `worker/src/main.py`
- Create: `worker/src/config.py`
- Create: `frontend/Dockerfile`

- [ ] **Step 1: Create `.env.example`**

```env
ANTHROPIC_API_KEY=sk-ant-...
CLASSIFICATION_MODEL=claude-sonnet-4-20250514
EXTRACTION_MODEL=claude-haiku-4-20250514
GENERAL_SPEC_THRESHOLD=10
DOMAIN_SPEC_THRESHOLD=20
SIMMER_ITERATIONS=5
CHUNK_SIZE=2000
WORKER_POLL_INTERVAL=5
```

- [ ] **Step 2: Create orchestrator `pyproject.toml`**

```toml
[project]
name = "orrery-orchestrator"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "anthropic>=0.40.0",
    "python-multipart>=0.0.9",
    "sentence-transformers>=3.0.0",
    "numpy>=1.26.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 3: Create `orchestrator/src/config.py`**

```python
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    classification_model: str = "claude-sonnet-4-20250514"
    extraction_model: str = "claude-haiku-4-20250514"
    general_spec_threshold: int = 10
    domain_spec_threshold: int = 20
    simmer_iterations: int = 5
    chunk_size: int = 2000
    worker_poll_interval: int = 5
    db_path: str = "/data/orrery.db"
    documents_dir: str = "/data/documents"
    specs_dir: str = "/data/specs"

def get_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        classification_model=os.environ.get("CLASSIFICATION_MODEL", "claude-sonnet-4-20250514"),
        extraction_model=os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-20250514"),
        general_spec_threshold=int(os.environ.get("GENERAL_SPEC_THRESHOLD", "10")),
        domain_spec_threshold=int(os.environ.get("DOMAIN_SPEC_THRESHOLD", "20")),
        simmer_iterations=int(os.environ.get("SIMMER_ITERATIONS", "5")),
        chunk_size=int(os.environ.get("CHUNK_SIZE", "2000")),
        worker_poll_interval=int(os.environ.get("WORKER_POLL_INTERVAL", "5")),
        db_path=os.environ.get("DB_PATH", "/data/orrery.db"),
        documents_dir=os.environ.get("DOCUMENTS_DIR", "/data/documents"),
        specs_dir=os.environ.get("SPECS_DIR", "/data/specs"),
    )
```

- [ ] **Step 4: Create `orchestrator/src/main.py`** (minimal FastAPI app)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db(settings.db_path)
    yield

app = FastAPI(title="Noospheric Orrery", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Create worker `pyproject.toml`**

```toml
[project]
name = "orrery-worker"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "simmer-sdk>=0.1.0",
    "sentence-transformers>=3.0.0",
    "numpy>=1.26.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 6: Create `worker/src/config.py`** (same as orchestrator config)

- [ ] **Step 7: Create `worker/src/main.py`** (stub poll loop)

```python
import asyncio
import sys
from .config import get_settings
from .db import init_db

async def poll_loop():
    settings = get_settings()
    init_db(settings.db_path)
    print(f"Worker started, polling every {settings.worker_poll_interval}s", flush=True)
    while True:
        # Job runner will be added in Task 11
        await asyncio.sleep(settings.worker_poll_interval)

def main():
    asyncio.run(poll_loop())

if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Create `orchestrator/Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY src/ src/
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 9: Create `worker/Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY src/ src/
CMD ["python", "-m", "src.main"]
```

- [ ] **Step 10: Create `frontend/Dockerfile`** (stub — Next.js setup in Task 10)

```dockerfile
FROM node:22-slim
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
```

- [ ] **Step 11: Create `docker-compose.yml`**

```yaml
services:
  orchestrator:
    build: ./orchestrator
    ports:
      - "8000:8000"
    volumes:
      - orrery-data:/data
    env_file: .env
    depends_on: []

  worker:
    build: ./worker
    volumes:
      - orrery-data:/data
    env_file: .env
    depends_on: []

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
    depends_on:
      - orchestrator

volumes:
  orrery-data:
```

- [ ] **Step 12: Verify orchestrator starts locally**

Run: `cd orchestrator && pip install -e ".[dev]" && python -m uvicorn src.main:app --port 8000`
Expected: Server starts, `curl localhost:8000/health` returns `{"status":"ok"}`

- [ ] **Step 13: Commit**

```bash
git add orchestrator/ worker/ frontend/Dockerfile docker-compose.yml .env.example
git commit -m "feat: scaffold orchestrator, worker, frontend containers with docker compose"
```

---

## Task 2: SQLite Database Layer

**Files:**
- Create: `orchestrator/src/db.py`
- Create: `orchestrator/tests/__init__.py`
- Create: `orchestrator/tests/conftest.py`
- Create: `orchestrator/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
# orchestrator/tests/test_db.py
import sqlite3
import tempfile
import os
from src.db import init_db, get_connection

def test_init_db_creates_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert "documents" in tables
    assert "chunks" in tables
    assert "domains" in tables
    assert "entities" in tables
    assert "entity_sources" in tables
    assert "merge_map" in tables
    assert "relationships" in tables
    assert "jobs" in tables
    assert "specs" in tables
    assert "document_domains" in tables
    assert "domain_merge_map" in tables

def test_init_db_enables_wal(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    conn.close()
    assert mode == "wal"

def test_init_db_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    init_db(db_path)  # Should not raise
    conn = get_connection(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert "documents" in tables
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Create conftest.py**

```python
# orchestrator/tests/conftest.py
import pytest
from src.db import init_db, get_connection

@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path
```

- [ ] **Step 4: Write `orchestrator/src/db.py`**

```python
import sqlite3
import os
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT,
    source_path TEXT,
    content TEXT,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT REFERENCES documents(id),
    chunk_index INTEGER,
    offset INTEGER,
    length INTEGER,
    text TEXT
);

CREATE TABLE IF NOT EXISTS domains (
    id TEXT PRIMARY KEY,
    path TEXT UNIQUE,
    parent_path TEXT,
    document_count INTEGER DEFAULT 0,
    spec_version INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS domain_merge_map (
    from_label TEXT PRIMARY KEY,
    to_path TEXT REFERENCES domains(path)
);

CREATE TABLE IF NOT EXISTS document_domains (
    document_id TEXT REFERENCES documents(id),
    domain_path TEXT REFERENCES domains(path),
    is_primary BOOLEAN,
    confidence REAL,
    PRIMARY KEY (document_id, domain_path)
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    canonical_name TEXT,
    type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entity_sources (
    entity_id TEXT REFERENCES entities(id),
    document_id TEXT REFERENCES documents(id),
    chunk_id TEXT REFERENCES chunks(id),
    extraction_pass TEXT,
    spec_version INTEGER
);

CREATE TABLE IF NOT EXISTS merge_map (
    from_name TEXT PRIMARY KEY,
    to_entity_id TEXT REFERENCES entities(id)
);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    from_entity TEXT REFERENCES entities(id),
    to_entity TEXT REFERENCES entities(id),
    type TEXT,
    weight REAL,
    source_chunk TEXT REFERENCES chunks(id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT,
    target TEXT,
    status TEXT DEFAULT 'queued',
    config TEXT,
    result TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS specs (
    id TEXT PRIMARY KEY,
    domain_path TEXT,
    version INTEGER,
    spec_content TEXT,
    golden_set TEXT,
    score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    conn.close()

def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_db.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add orchestrator/src/db.py orchestrator/tests/
git commit -m "feat: SQLite database layer with WAL mode and full schema"
```

---

## Task 3: Document Chunking

**Files:**
- Create: `orchestrator/src/pipeline/__init__.py`
- Create: `orchestrator/src/pipeline/chunker.py`
- Create: `orchestrator/src/pipeline/excerpt.py`
- Create: `orchestrator/tests/test_chunker.py`
- Create: `orchestrator/tests/test_excerpt.py`

- [ ] **Step 1: Write failing tests for chunker**

```python
# orchestrator/tests/test_chunker.py
from src.pipeline.chunker import chunk_document

def test_short_document_single_chunk():
    text = "This is a short document."
    chunks = chunk_document(text, chunk_size=2000)
    assert len(chunks) == 1
    assert chunks[0]["text"] == text
    assert chunks[0]["offset"] == 0
    assert chunks[0]["length"] == len(text)

def test_long_document_multiple_chunks():
    text = "word " * 1000  # 5000 chars
    chunks = chunk_document(text, chunk_size=2000)
    assert len(chunks) >= 2
    # Verify no gaps — chunks cover entire document
    for i, chunk in enumerate(chunks):
        assert chunk["chunk_index"] == i
        assert chunk["text"] == text[chunk["offset"]:chunk["offset"] + chunk["length"]]

def test_chunks_have_overlap():
    text = "word " * 1000
    chunks = chunk_document(text, chunk_size=2000, overlap=200)
    if len(chunks) > 1:
        # Second chunk starts before first chunk ends
        assert chunks[1]["offset"] < chunks[0]["offset"] + chunks[0]["length"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_chunker.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement chunker**

```python
# orchestrator/src/pipeline/chunker.py

def chunk_document(
    text: str,
    chunk_size: int = 2000,
    overlap: int = 200,
) -> list[dict]:
    if len(text) <= chunk_size:
        return [{"chunk_index": 0, "offset": 0, "length": len(text), "text": text}]

    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append({
            "chunk_index": idx,
            "offset": start,
            "length": end - start,
            "text": text[start:end],
        })
        idx += 1
        start = end - overlap if end < len(text) else end
    return chunks
```

- [ ] **Step 4: Run chunker tests**

Run: `cd orchestrator && python -m pytest tests/test_chunker.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Write failing tests for excerpt builder**

```python
# orchestrator/tests/test_excerpt.py
from src.pipeline.excerpt import build_classification_excerpt

def test_short_doc_returns_full():
    text = "Short document content."
    excerpt = build_classification_excerpt("My Title", text)
    assert "My Title" in excerpt
    assert "Short document content." in excerpt

def test_long_doc_samples_three_windows():
    text = "A" * 3000 + "B" * 3000 + "C" * 3000  # 9K chars
    excerpt = build_classification_excerpt("Title", text)
    assert "Title" in excerpt
    assert "A" in excerpt  # beginning
    assert "B" in excerpt  # middle
    assert "C" in excerpt  # end
    assert len(excerpt) < len(text)  # actually shorter

def test_medium_doc_returns_full():
    text = "Content " * 500  # ~4K chars, under 6K
    excerpt = build_classification_excerpt("Title", text)
    assert text in excerpt
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_excerpt.py -v`
Expected: FAIL

- [ ] **Step 7: Implement excerpt builder**

```python
# orchestrator/src/pipeline/excerpt.py

def build_classification_excerpt(title: str, content: str, max_window: int = 2000) -> str:
    header = f"Title: {title}\n\n"

    if len(content) <= 6000:
        return header + content

    begin = content[:max_window]
    mid_start = (len(content) - max_window) // 2
    middle = content[mid_start:mid_start + max_window]
    end = content[-max_window:]

    return (
        header
        + "--- Beginning ---\n" + begin + "\n\n"
        + "--- Middle ---\n" + middle + "\n\n"
        + "--- End ---\n" + end
    )
```

- [ ] **Step 8: Run excerpt tests**

Run: `cd orchestrator && python -m pytest tests/test_excerpt.py -v`
Expected: 3 PASSED

- [ ] **Step 9: Commit**

```bash
git add orchestrator/src/pipeline/ orchestrator/tests/test_chunker.py orchestrator/tests/test_excerpt.py
git commit -m "feat: document chunking with overlap and adaptive classification excerpts"
```

---

## Task 4: Pydantic Models

**Files:**
- Create: `orchestrator/src/models.py`

- [ ] **Step 1: Create Pydantic models for API request/response**

```python
# orchestrator/src/models.py
from pydantic import BaseModel
from datetime import datetime

# --- Documents ---
class DocumentSummary(BaseModel):
    id: str
    title: str
    status: str
    created_at: datetime
    domains: list[str] = []
    entity_count: int = 0

class DocumentDetail(BaseModel):
    id: str
    title: str
    source_path: str | None
    content: str
    metadata: dict | None
    status: str
    created_at: datetime
    domains: list[dict]  # [{path, is_primary, confidence}]
    entities: list[dict]  # [{id, canonical_name, type}]

# --- Domains ---
class DomainInfo(BaseModel):
    id: str
    path: str
    parent_path: str | None
    document_count: int
    spec_version: int | None
    children: list["DomainInfo"] = []

# --- Entities ---
class EntitySummary(BaseModel):
    id: str
    canonical_name: str
    type: str
    source_count: int = 0
    domains: list[str] = []

class EntityDetail(BaseModel):
    id: str
    canonical_name: str
    type: str
    created_at: datetime
    sources: list[dict]  # [{document_id, chunk_id, extraction_pass}]
    merge_history: list[str] = []

# --- Jobs ---
class JobInfo(BaseModel):
    id: str
    type: str
    target: str
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

# --- Stats ---
class Stats(BaseModel):
    document_count: int
    entity_count: int
    domain_count: int
    active_jobs: int

# --- Ingest ---
class IngestResult(BaseModel):
    document_id: str
    title: str
    domains: list[str]
    entity_count: int
    jobs_queued: list[str]

class DirectoryIngestRequest(BaseModel):
    path: str
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/src/models.py
git commit -m "feat: Pydantic models for API request/response"
```

---

## Task 5: Domain Classification (Sonnet)

**Files:**
- Create: `orchestrator/src/pipeline/classifier.py`
- Create: `orchestrator/tests/test_classifier.py`

- [ ] **Step 1: Write failing test**

```python
# orchestrator/tests/test_classifier.py
import json
from unittest.mock import AsyncMock, patch
from src.pipeline.classifier import classify_document

async def test_classify_returns_domains():
    mock_response = AsyncMock()
    mock_response.content = [
        AsyncMock(text=json.dumps({
            "primary_domain": "techniques/wet-blending",
            "secondary_domains": ["theory/color-theory"],
            "new_domains": [],
        }))
    ]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    result = await classify_document(
        client=mock_client,
        title="Wet Blending Tutorial",
        excerpt="How to wet blend on miniatures...",
        existing_taxonomy=["techniques", "theory"],
        model="claude-sonnet-4-20250514",
    )

    assert result["primary_domain"] == "techniques/wet-blending"
    assert "theory/color-theory" in result["secondary_domains"]
    mock_client.messages.create.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_classifier.py -v`
Expected: FAIL

- [ ] **Step 3: Implement classifier**

```python
# orchestrator/src/pipeline/classifier.py
import json
from anthropic import AsyncAnthropic

CLASSIFICATION_PROMPT = """You are a document classifier for a knowledge graph system. Given a document excerpt and existing domain taxonomy, classify the document.

Existing taxonomy:
{taxonomy}

Document:
{excerpt}

Respond with JSON only:
{{
    "primary_domain": "region/parent/subdomain",
    "secondary_domains": ["other/domains"],
    "new_domains": ["proposed/new/domains"],
    "confidence": 0.0-1.0
}}

Rules:
- Use existing domains when they fit (exact path match)
- Propose new domains only when nothing in the taxonomy covers the content
- Domain paths are hierarchical: region/parent/subdomain
- A document can have 1 primary and 0-3 secondary domains
"""

async def classify_document(
    client: AsyncAnthropic,
    title: str,
    excerpt: str,
    existing_taxonomy: list[str],
    model: str,
) -> dict:
    taxonomy_str = "\n".join(f"  - {d}" for d in existing_taxonomy) if existing_taxonomy else "  (empty — propose new domains)"

    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": CLASSIFICATION_PROMPT.format(
                taxonomy=taxonomy_str,
                excerpt=excerpt,
            ),
        }],
    )

    text = response.content[0].text
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)
```

- [ ] **Step 4: Run test**

Run: `cd orchestrator && python -m pytest tests/test_classifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/classifier.py orchestrator/tests/test_classifier.py
git commit -m "feat: Sonnet domain classification with taxonomy awareness"
```

---

## Task 6: Domain Normalization

**Files:**
- Create: `orchestrator/src/pipeline/domain_normalizer.py`
- Create: `orchestrator/tests/test_domain_normalizer.py`

- [ ] **Step 1: Write failing test**

```python
# orchestrator/tests/test_domain_normalizer.py
from src.pipeline.domain_normalizer import normalize_domain_label, assign_document_domains
from src.db import init_db, get_connection

def test_exact_match_in_merge_map(test_db):
    conn = get_connection(test_db)
    # Pre-populate merge map
    conn.execute("INSERT INTO domains (id, path) VALUES ('d1', 'techniques/blending')")
    conn.execute("INSERT INTO domain_merge_map (from_label, to_path) VALUES ('wet blending', 'techniques/blending')")
    conn.commit()

    result = normalize_domain_label(conn, "wet blending")
    assert result == "techniques/blending"
    conn.close()

def test_new_domain_inserted(test_db):
    conn = get_connection(test_db)
    result = normalize_domain_label(conn, "techniques/airbrush")
    assert result == "techniques/airbrush"
    # Should now exist in domains table
    row = conn.execute("SELECT path FROM domains WHERE path = ?", ("techniques/airbrush",)).fetchone()
    assert row is not None
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_domain_normalizer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement domain normalizer**

```python
# orchestrator/src/pipeline/domain_normalizer.py
import sqlite3
import uuid

def normalize_domain_label(conn: sqlite3.Connection, label: str) -> str:
    """Check merge map, then insert as new domain if not found.

    Full embedding-based normalization (steps 2-7 from spec) will be added
    when sentence-transformers integration is wired up. For now: merge map
    lookup + direct insert.
    """
    # Step 1: Check merge map
    row = conn.execute(
        "SELECT to_path FROM domain_merge_map WHERE from_label = ?",
        (label.lower().strip(),)
    ).fetchone()
    if row:
        return row[0]

    # Check if domain already exists
    row = conn.execute(
        "SELECT path FROM domains WHERE path = ?",
        (label,)
    ).fetchone()
    if row:
        return row[0]

    # Insert new domain
    parent_path = "/".join(label.split("/")[:-1]) or None
    conn.execute(
        "INSERT INTO domains (id, path, parent_path, document_count) VALUES (?, ?, ?, 0)",
        (str(uuid.uuid4()), label, parent_path),
    )
    conn.commit()
    return label


def assign_document_domains(
    conn: sqlite3.Connection,
    document_id: str,
    classification: dict,
) -> list[str]:
    """Normalize and assign domains from classification result to document."""
    all_domains = []

    primary = classification.get("primary_domain")
    if primary:
        path = normalize_domain_label(conn, primary)
        conn.execute(
            "INSERT OR REPLACE INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, ?, 1, ?)",
            (document_id, path, classification.get("confidence", 0.8)),
        )
        conn.execute(
            "UPDATE domains SET document_count = document_count + 1 WHERE path = ?",
            (path,),
        )
        all_domains.append(path)

    for secondary in classification.get("secondary_domains", []):
        path = normalize_domain_label(conn, secondary)
        conn.execute(
            "INSERT OR REPLACE INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, ?, 0, ?)",
            (document_id, path, 0.5),
        )
        conn.execute(
            "UPDATE domains SET document_count = document_count + 1 WHERE path = ?",
            (path,),
        )
        all_domains.append(path)

    for new_domain in classification.get("new_domains", []):
        normalize_domain_label(conn, new_domain)  # Insert but don't assign yet

    conn.commit()
    return all_domains
```

- [ ] **Step 4: Run tests**

Run: `cd orchestrator && python -m pytest tests/test_domain_normalizer.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/domain_normalizer.py orchestrator/tests/test_domain_normalizer.py
git commit -m "feat: domain normalization with merge map lookup"
```

---

## Task 7: Entity Extraction (Haiku with Spec)

**Files:**
- Create: `orchestrator/src/pipeline/extractor.py`
- Create: `orchestrator/tests/test_extractor.py`

- [ ] **Step 1: Write failing test**

```python
# orchestrator/tests/test_extractor.py
import json
from unittest.mock import AsyncMock
from src.pipeline.extractor import extract_entities_from_chunk

async def test_extract_entities_returns_list():
    mock_response = AsyncMock()
    mock_response.content = [
        AsyncMock(text=json.dumps({
            "entities": [
                {"name": "wet blending", "type": "Technique"},
                {"name": "Duncan Rhodes", "type": "Person"},
            ]
        }))
    ]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    spec = "Extract entities: Person, Technique, Thing from this text."
    entities = await extract_entities_from_chunk(
        client=mock_client,
        chunk_text="Duncan Rhodes demonstrates wet blending...",
        spec=spec,
        model="claude-haiku-4-20250514",
    )

    assert len(entities) == 2
    assert entities[0]["name"] == "wet blending"
    assert entities[0]["type"] == "Technique"
    assert entities[1]["name"] == "Duncan Rhodes"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_extractor.py -v`
Expected: FAIL

- [ ] **Step 3: Implement extractor**

```python
# orchestrator/src/pipeline/extractor.py
import json
from anthropic import AsyncAnthropic

EXTRACTION_WRAPPER = """You are an entity extraction system. Follow the extraction spec below exactly.

EXTRACTION SPEC:
{spec}

TEXT TO EXTRACT FROM:
{chunk_text}

Respond with JSON only:
{{
    "entities": [
        {{"name": "entity name", "type": "EntityType"}}
    ]
}}

Rules:
- Only extract entities explicitly mentioned in the text
- Do not hallucinate or infer entities not present
- Use the entity types defined in the spec
- Normalize names: lowercase, strip extra whitespace
"""

async def extract_entities_from_chunk(
    client: AsyncAnthropic,
    chunk_text: str,
    spec: str,
    model: str,
) -> list[dict]:
    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": EXTRACTION_WRAPPER.format(spec=spec, chunk_text=chunk_text),
        }],
    )

    text = response.content[0].text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    result = json.loads(text)
    return result.get("entities", [])


async def extract_document(
    client: AsyncAnthropic,
    chunks: list[dict],
    spec: str,
    model: str,
) -> list[dict]:
    """Extract entities from all chunks, deduplicate within document."""
    all_entities = []
    seen = set()

    for chunk in chunks:
        entities = await extract_entities_from_chunk(
            client=client,
            chunk_text=chunk["text"],
            spec=spec,
            model=model,
        )
        for entity in entities:
            key = (entity["name"].lower().strip(), entity["type"])
            if key not in seen:
                seen.add(key)
                entity["chunk_id"] = chunk.get("id")
                all_entities.append(entity)

    return all_entities
```

- [ ] **Step 4: Run test**

Run: `cd orchestrator && python -m pytest tests/test_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/extractor.py orchestrator/tests/test_extractor.py
git commit -m "feat: Haiku entity extraction with spec wrapper and deduplication"
```

---

## Task 8: Entity Normalization + Co-occurrence

**Files:**
- Create: `orchestrator/src/pipeline/normalizer.py`
- Create: `orchestrator/src/pipeline/cooccurrence.py`
- Create: `orchestrator/tests/test_normalizer.py`
- Create: `orchestrator/tests/test_cooccurrence.py`

- [ ] **Step 1: Write failing tests for normalizer**

```python
# orchestrator/tests/test_normalizer.py
from src.pipeline.normalizer import normalize_entity
from src.db import init_db, get_connection

def test_merge_map_hit(test_db):
    conn = get_connection(test_db)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'wet blending', 'Technique')")
    conn.execute("INSERT INTO merge_map (from_name, to_entity_id) VALUES ('wet-blending', 'e1')")
    conn.commit()

    entity_id = normalize_entity(conn, "wet-blending", "Technique")
    assert entity_id == "e1"
    conn.close()

def test_exact_match_existing(test_db):
    conn = get_connection(test_db)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'wet blending', 'Technique')")
    conn.commit()

    entity_id = normalize_entity(conn, "wet blending", "Technique")
    assert entity_id == "e1"
    conn.close()

def test_new_entity_inserted(test_db):
    conn = get_connection(test_db)
    entity_id = normalize_entity(conn, "drybrushing", "Technique")
    assert entity_id is not None
    row = conn.execute("SELECT canonical_name FROM entities WHERE id = ?", (entity_id,)).fetchone()
    assert row[0] == "drybrushing"
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_normalizer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement normalizer**

```python
# orchestrator/src/pipeline/normalizer.py
import sqlite3
import uuid

def normalize_entity(conn: sqlite3.Connection, name: str, entity_type: str) -> str:
    """Normalize an entity name. Returns entity ID.

    Current: merge_map lookup + exact match + insert.
    Future: add embedding similarity comparison for fuzzy matching.
    """
    clean_name = name.lower().strip()

    # Check merge map
    row = conn.execute(
        "SELECT to_entity_id FROM merge_map WHERE from_name = ?",
        (clean_name,)
    ).fetchone()
    if row:
        return row[0]

    # Check exact match
    row = conn.execute(
        "SELECT id FROM entities WHERE canonical_name = ? AND type = ?",
        (clean_name, entity_type),
    ).fetchone()
    if row:
        return row[0]

    # Insert new entity
    entity_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, ?)",
        (entity_id, clean_name, entity_type),
    )
    conn.commit()
    return entity_id
```

- [ ] **Step 4: Run normalizer tests**

Run: `cd orchestrator && python -m pytest tests/test_normalizer.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Write failing tests for co-occurrence**

```python
# orchestrator/tests/test_cooccurrence.py
from src.pipeline.cooccurrence import compute_cooccurrence_edges

def test_entities_in_same_chunk_get_edge():
    # chunk_entities maps chunk_id -> list of entity_ids
    chunk_entities = {
        "c1": ["e1", "e2", "e3"],
        "c2": ["e1", "e2"],
    }
    edges = compute_cooccurrence_edges(chunk_entities)
    # e1-e2 co-occur in both chunks, weight=2
    e1_e2 = [e for e in edges if set([e["from"], e["to"]]) == {"e1", "e2"}]
    assert len(e1_e2) == 1
    assert e1_e2[0]["weight"] == 2

def test_single_entity_chunk_no_edges():
    chunk_entities = {"c1": ["e1"]}
    edges = compute_cooccurrence_edges(chunk_entities)
    assert len(edges) == 0

def test_edge_has_source_chunk():
    chunk_entities = {"c1": ["e1", "e2"]}
    edges = compute_cooccurrence_edges(chunk_entities)
    assert edges[0]["source_chunk"] == "c1"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_cooccurrence.py -v`
Expected: FAIL

- [ ] **Step 7: Implement co-occurrence**

```python
# orchestrator/src/pipeline/cooccurrence.py
from itertools import combinations
from collections import defaultdict
import uuid

def compute_cooccurrence_edges(chunk_entities: dict[str, list[str]]) -> list[dict]:
    """Compute co-occurrence edges from chunk-to-entity mappings.

    Args:
        chunk_entities: {chunk_id: [entity_id, ...]}

    Returns:
        List of edge dicts with from, to, type, weight, source_chunk.
        Weight = number of chunks the pair co-occurs in.
    """
    pair_weight: dict[tuple[str, str], int] = defaultdict(int)
    pair_first_chunk: dict[tuple[str, str], str] = {}

    for chunk_id, entity_ids in chunk_entities.items():
        for a, b in combinations(sorted(set(entity_ids)), 2):
            pair = (a, b)
            pair_weight[pair] += 1
            if pair not in pair_first_chunk:
                pair_first_chunk[pair] = chunk_id

    edges = []
    for (a, b), weight in pair_weight.items():
        edges.append({
            "id": str(uuid.uuid4()),
            "from": a,
            "to": b,
            "type": "co_occurs",
            "weight": weight,
            "source_chunk": pair_first_chunk[(a, b)],
        })
    return edges
```

- [ ] **Step 8: Run co-occurrence tests**

Run: `cd orchestrator && python -m pytest tests/test_cooccurrence.py -v`
Expected: 3 PASSED

- [ ] **Step 9: Commit**

```bash
git add orchestrator/src/pipeline/normalizer.py orchestrator/src/pipeline/cooccurrence.py orchestrator/tests/test_normalizer.py orchestrator/tests/test_cooccurrence.py
git commit -m "feat: entity normalization with merge map and co-occurrence edge computation"
```

---

## Task 9: Ingest Route (the core pipeline wiring)

**Files:**
- Create: `orchestrator/src/routes/__init__.py`
- Create: `orchestrator/src/routes/ingest.py`
- Create: `orchestrator/tests/test_ingest_route.py`
- Modify: `orchestrator/src/main.py` (register routes)

- [ ] **Step 1: Write failing integration test**

```python
# orchestrator/tests/test_ingest_route.py
import io
import json
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

# Mock anthropic before importing app
with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
    from src.main import app

client = TestClient(app)

def test_ingest_stores_document_and_classifies(tmp_path):
    """Upload a file, verify it's stored and classified."""
    mock_classify_result = {
        "primary_domain": "techniques/blending",
        "secondary_domains": [],
        "new_domains": [],
        "confidence": 0.9,
    }

    with patch("src.routes.ingest.classify_document", new_callable=AsyncMock, return_value=mock_classify_result):
        with patch("src.routes.ingest.get_settings") as mock_settings:
            mock_settings.return_value.db_path = str(tmp_path / "test.db")
            mock_settings.return_value.documents_dir = str(tmp_path / "docs")
            mock_settings.return_value.classification_model = "claude-sonnet-4-20250514"
            mock_settings.return_value.extraction_model = "claude-haiku-4-20250514"
            mock_settings.return_value.chunk_size = 2000
            mock_settings.return_value.anthropic_api_key = "test-key"
            mock_settings.return_value.general_spec_threshold = 10
            mock_settings.return_value.domain_spec_threshold = 20

            # Need to init DB for test
            from src.db import init_db
            init_db(str(tmp_path / "test.db"))

            response = client.post(
                "/ingest",
                files={"file": ("test.txt", io.BytesIO(b"Document content about blending"), "text/plain")},
            )

    assert response.status_code == 200
    result = response.json()
    assert "document_id" in result
    assert "techniques/blending" in result["domains"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_ingest_route.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ingest route**

```python
# orchestrator/src/routes/ingest.py
import uuid
import os
import json
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from anthropic import AsyncAnthropic

from ..config import get_settings
from ..db import get_connection
from ..models import IngestResult, DirectoryIngestRequest
from ..pipeline.chunker import chunk_document
from ..pipeline.excerpt import build_classification_excerpt
from ..pipeline.classifier import classify_document
from ..pipeline.domain_normalizer import assign_document_domains
from ..pipeline.extractor import extract_document
from ..pipeline.normalizer import normalize_entity
from ..pipeline.cooccurrence import compute_cooccurrence_edges

router = APIRouter()

async def _ingest_document(title: str, content: str, source_path: str | None) -> dict:
    settings = get_settings()
    conn = get_connection(settings.db_path)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    doc_id = str(uuid.uuid4())

    # 1. Store document
    conn.execute(
        "INSERT INTO documents (id, title, source_path, content, status) VALUES (?, ?, ?, ?, 'pending')",
        (doc_id, title, source_path, content),
    )

    # 1b. Chunk and store
    chunks = chunk_document(content, chunk_size=settings.chunk_size)
    for chunk in chunks:
        chunk["id"] = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) VALUES (?, ?, ?, ?, ?, ?)",
            (chunk["id"], doc_id, chunk["chunk_index"], chunk["offset"], chunk["length"], chunk["text"]),
        )
    conn.commit()

    # 2. Classify
    excerpt = build_classification_excerpt(title, content)
    taxonomy = [row[0] for row in conn.execute("SELECT path FROM domains ORDER BY path").fetchall()]

    classification = await classify_document(
        client=client,
        title=title,
        excerpt=excerpt,
        existing_taxonomy=taxonomy,
        model=settings.classification_model,
    )

    domains = assign_document_domains(conn, doc_id, classification)
    conn.execute("UPDATE documents SET status = 'classified' WHERE id = ?", (doc_id,))
    conn.commit()

    # 3. Extract if general spec exists
    entity_count = 0
    spec_row = conn.execute(
        "SELECT spec_content, version FROM specs WHERE domain_path IS NULL ORDER BY version DESC LIMIT 1"
    ).fetchone()

    if spec_row:
        spec = spec_row[0]
        spec_version = spec_row[1]
        entities = await extract_document(
            client=client,
            chunks=chunks,
            spec=spec,
            model=settings.extraction_model,
        )

        # Normalize and insert entities
        chunk_entities: dict[str, list[str]] = {}
        for entity in entities:
            entity_id = normalize_entity(conn, entity["name"], entity["type"])
            conn.execute(
                "INSERT INTO entity_sources (entity_id, document_id, chunk_id, extraction_pass, spec_version) VALUES (?, ?, ?, 'general', ?)",
                (entity_id, doc_id, entity.get("chunk_id"), spec_version),
            )
            chunk_id = entity.get("chunk_id")
            if chunk_id:
                chunk_entities.setdefault(chunk_id, []).append(entity_id)

        # Co-occurrence edges
        edges = compute_cooccurrence_edges(chunk_entities)
        for edge in edges:
            conn.execute(
                "INSERT INTO relationships (id, from_entity, to_entity, type, weight, source_chunk) VALUES (?, ?, ?, ?, ?, ?)",
                (edge["id"], edge["from"], edge["to"], edge["type"], edge["weight"], edge["source_chunk"]),
            )

        entity_count = len(entities)
        conn.execute("UPDATE documents SET status = 'extracted' WHERE id = ?", (doc_id,))
        conn.commit()

    # 4. Check thresholds
    jobs_queued = []

    # Auto-trigger general spec simmering if none exists
    if not spec_row:
        existing_general_job = conn.execute(
            "SELECT id FROM jobs WHERE type = 'simmer_general' AND status IN ('queued', 'running')"
        ).fetchone()
        if not existing_general_job:
            job_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO jobs (id, type, target, status) VALUES (?, 'simmer_general', 'general', 'queued')",
                (job_id,),
            )
            jobs_queued.append(job_id)

    # Check domain thresholds
    for domain_path in domains:
        domain = conn.execute(
            "SELECT document_count, spec_version FROM domains WHERE path = ?",
            (domain_path,),
        ).fetchone()
        if domain and domain[0] >= settings.domain_spec_threshold and domain[1] is None:
            existing_job = conn.execute(
                "SELECT id FROM jobs WHERE type = 'simmer_domain' AND target = ? AND status IN ('queued', 'running')",
                (domain_path,),
            ).fetchone()
            if not existing_job:
                job_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'simmer_domain', ?, 'queued', ?)",
                    (job_id, domain_path, json.dumps({"domain": domain_path})),
                )
                jobs_queued.append(job_id)

    conn.commit()
    conn.close()

    return {
        "document_id": doc_id,
        "title": title,
        "domains": domains,
        "entity_count": entity_count,
        "jobs_queued": jobs_queued,
    }


@router.post("/ingest", response_model=IngestResult)
async def ingest_file(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8")
    title = file.filename or "untitled"

    settings = get_settings()
    os.makedirs(settings.documents_dir, exist_ok=True)
    doc_path = os.path.join(settings.documents_dir, f"{uuid.uuid4()}_{title}")
    with open(doc_path, "w") as f:
        f.write(content)

    return await _ingest_document(title, content, doc_path)


@router.post("/ingest/directory")
async def ingest_directory(request: DirectoryIngestRequest):
    dir_path = Path(request.path)
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {request.path}")

    results = []
    for file_path in sorted(dir_path.rglob("*")):
        if file_path.is_file() and file_path.suffix in (".txt", ".md", ".json", ".csv"):
            content = file_path.read_text(errors="replace")
            result = await _ingest_document(file_path.stem, content, str(file_path))
            results.append(result)

    return {"documents": results, "total": len(results)}
```

- [ ] **Step 4: Register routes in main.py**

```python
# Add to orchestrator/src/main.py after app creation:
from .routes.ingest import router as ingest_router
app.include_router(ingest_router)
```

- [ ] **Step 5: Run integration test**

Run: `cd orchestrator && python -m pytest tests/test_ingest_route.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/src/routes/ orchestrator/src/main.py orchestrator/tests/test_ingest_route.py
git commit -m "feat: ingest route with classify + extract + co-occurrence pipeline"
```

---

## Task 10: Read-Only API Routes

**Files:**
- Create: `orchestrator/src/routes/documents.py`
- Create: `orchestrator/src/routes/domains.py`
- Create: `orchestrator/src/routes/entities.py`
- Create: `orchestrator/src/routes/jobs.py`
- Create: `orchestrator/src/routes/simmer.py`
- Create: `orchestrator/src/routes/stats.py`
- Create: `orchestrator/tests/test_read_routes.py`
- Modify: `orchestrator/src/main.py` (register all routes)

- [ ] **Step 1: Write failing test for stats endpoint**

```python
# orchestrator/tests/test_read_routes.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.db import init_db, get_connection

with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
    from src.main import app

client = TestClient(app)

def test_stats_returns_counts(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc 1', 'extracted')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'test', 'Thing')")
    conn.execute("INSERT INTO domains (id, path) VALUES ('dm1', 'techniques')")
    conn.commit()
    conn.close()

    with patch("src.routes.stats.get_settings") as mock:
        mock.return_value.db_path = db_path
        response = client.get("/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["document_count"] == 1
    assert data["entity_count"] == 1
    assert data["domain_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_read_routes.py -v`
Expected: FAIL

- [ ] **Step 3: Implement stats route**

```python
# orchestrator/src/routes/stats.py
from fastapi import APIRouter
from ..config import get_settings
from ..db import get_connection
from ..models import Stats

router = APIRouter()

@router.get("/stats", response_model=Stats)
def get_stats():
    settings = get_settings()
    conn = get_connection(settings.db_path)
    docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    domains = conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')").fetchone()[0]
    conn.close()
    return Stats(document_count=docs, entity_count=entities, domain_count=domains, active_jobs=active)
```

- [ ] **Step 4: Implement documents route**

```python
# orchestrator/src/routes/documents.py
from fastapi import APIRouter, HTTPException
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.get("/documents")
def list_documents(limit: int = 50, offset: int = 0):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    rows = conn.execute(
        """SELECT d.id, d.title, d.status, d.created_at,
                  GROUP_CONCAT(dd.domain_path) as domains,
                  (SELECT COUNT(*) FROM entity_sources es WHERE es.document_id = d.id) as entity_count
           FROM documents d
           LEFT JOIN document_domains dd ON d.id = dd.document_id
           GROUP BY d.id
           ORDER BY d.created_at DESC
           LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "title": r[1], "status": r[2], "created_at": r[3],
            "domains": r[4].split(",") if r[4] else [],
            "entity_count": r[5],
        }
        for r in rows
    ]

@router.get("/documents/{document_id}")
def get_document(document_id: str):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not doc:
        conn.close()
        raise HTTPException(status_code=404, detail="Document not found")

    domains = conn.execute(
        "SELECT domain_path, is_primary, confidence FROM document_domains WHERE document_id = ?",
        (document_id,),
    ).fetchall()

    entities = conn.execute(
        """SELECT DISTINCT e.id, e.canonical_name, e.type
           FROM entities e
           JOIN entity_sources es ON e.id = es.entity_id
           WHERE es.document_id = ?""",
        (document_id,),
    ).fetchall()
    conn.close()

    return {
        "id": doc["id"], "title": doc["title"], "source_path": doc["source_path"],
        "content": doc["content"], "metadata": doc["metadata"], "status": doc["status"],
        "created_at": doc["created_at"],
        "domains": [{"path": d[0], "is_primary": bool(d[1]), "confidence": d[2]} for d in domains],
        "entities": [{"id": e[0], "canonical_name": e[1], "type": e[2]} for e in entities],
    }
```

- [ ] **Step 5: Implement domains route**

```python
# orchestrator/src/routes/domains.py
from fastapi import APIRouter
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.get("/domains")
def list_domains():
    settings = get_settings()
    conn = get_connection(settings.db_path)
    rows = conn.execute(
        "SELECT id, path, parent_path, document_count, spec_version, created_at FROM domains ORDER BY path"
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "path": r[1], "parent_path": r[2],
            "document_count": r[3], "spec_version": r[4], "created_at": r[5],
        }
        for r in rows
    ]
```

- [ ] **Step 6: Implement entities route**

```python
# orchestrator/src/routes/entities.py
from fastapi import APIRouter, HTTPException
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.get("/entities")
def list_entities(
    limit: int = 50,
    offset: int = 0,
    type: str | None = None,
    domain: str | None = None,
):
    settings = get_settings()
    conn = get_connection(settings.db_path)

    query = """
        SELECT e.id, e.canonical_name, e.type,
               (SELECT COUNT(*) FROM entity_sources es WHERE es.entity_id = e.id) as source_count
        FROM entities e
    """
    params: list = []

    if domain:
        query += """
            JOIN entity_sources es2 ON e.id = es2.entity_id
            JOIN document_domains dd ON es2.document_id = dd.document_id AND dd.domain_path = ?
        """
        params.append(domain)

    if type:
        query += " WHERE e.type = ?" if "WHERE" not in query else " AND e.type = ?"
        params.append(type)

    query += " GROUP BY e.id ORDER BY source_count DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [
        {"id": r[0], "canonical_name": r[1], "type": r[2], "source_count": r[3]}
        for r in rows
    ]

@router.get("/entities/{entity_id}")
def get_entity(entity_id: str):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    entity = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if not entity:
        conn.close()
        raise HTTPException(status_code=404, detail="Entity not found")

    sources = conn.execute(
        "SELECT document_id, chunk_id, extraction_pass, spec_version FROM entity_sources WHERE entity_id = ?",
        (entity_id,),
    ).fetchall()

    merges = conn.execute(
        "SELECT from_name FROM merge_map WHERE to_entity_id = ?",
        (entity_id,),
    ).fetchall()
    conn.close()

    return {
        "id": entity["id"], "canonical_name": entity["canonical_name"],
        "type": entity["type"], "created_at": entity["created_at"],
        "sources": [{"document_id": s[0], "chunk_id": s[1], "extraction_pass": s[2], "spec_version": s[3]} for s in sources],
        "merge_history": [m[0] for m in merges],
    }
```

- [ ] **Step 7: Implement jobs route**

```python
# orchestrator/src/routes/jobs.py
from fastapi import APIRouter
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.get("/jobs")
def list_jobs(status: str | None = None):
    settings = get_settings()
    conn = get_connection(settings.db_path)
    if status:
        rows = conn.execute(
            "SELECT id, type, target, status, created_at, started_at, completed_at FROM jobs WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, type, target, status, created_at, started_at, completed_at FROM jobs ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "type": r[1], "target": r[2], "status": r[3],
            "created_at": r[4], "started_at": r[5], "completed_at": r[6],
        }
        for r in rows
    ]
```

- [ ] **Step 8: Implement simmer trigger route**

```python
# orchestrator/src/routes/simmer.py
import uuid
import json
from fastapi import APIRouter, HTTPException
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

@router.post("/simmer/general")
def trigger_general_simmer():
    settings = get_settings()
    conn = get_connection(settings.db_path)

    existing = conn.execute(
        "SELECT id FROM jobs WHERE type = 'simmer_general' AND status IN ('queued', 'running')"
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail="General simmer already in progress")

    job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status) VALUES (?, 'simmer_general', 'general', 'queued')",
        (job_id,),
    )
    conn.commit()
    conn.close()
    return {"job_id": job_id, "status": "queued"}

@router.post("/simmer/{domain_path:path}")
def trigger_domain_simmer(domain_path: str):
    settings = get_settings()
    conn = get_connection(settings.db_path)

    domain = conn.execute("SELECT path FROM domains WHERE path = ?", (domain_path,)).fetchone()
    if not domain:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Domain not found: {domain_path}")

    existing = conn.execute(
        "SELECT id FROM jobs WHERE type = 'simmer_domain' AND target = ? AND status IN ('queued', 'running')",
        (domain_path,),
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail=f"Domain simmer already in progress for {domain_path}")

    job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'simmer_domain', ?, 'queued', ?)",
        (job_id, domain_path, json.dumps({"domain": domain_path})),
    )
    conn.commit()
    conn.close()
    return {"job_id": job_id, "status": "queued"}
```

- [ ] **Step 9: Register all routes in main.py**

```python
# orchestrator/src/main.py — full updated version
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .db import init_db
from .routes.ingest import router as ingest_router
from .routes.documents import router as documents_router
from .routes.domains import router as domains_router
from .routes.entities import router as entities_router
from .routes.jobs import router as jobs_router
from .routes.simmer import router as simmer_router
from .routes.stats import router as stats_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db(settings.db_path)
    yield

app = FastAPI(title="Noospheric Orrery", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(ingest_router)
app.include_router(documents_router)
app.include_router(domains_router)
app.include_router(entities_router)
app.include_router(jobs_router)
app.include_router(simmer_router)
app.include_router(stats_router)

@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 10: Run all tests**

Run: `cd orchestrator && python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 11: Commit**

```bash
git add orchestrator/src/routes/ orchestrator/src/main.py orchestrator/tests/test_read_routes.py
git commit -m "feat: all API routes — documents, domains, entities, jobs, simmer, stats"
```

---

## Task 11: Simmer Worker — Job Runner

**Files:**
- Create: `worker/src/db.py` (copy from orchestrator)
- Create: `worker/src/jobs/__init__.py`
- Create: `worker/src/jobs/runner.py`
- Create: `worker/tests/__init__.py`
- Create: `worker/tests/conftest.py`
- Create: `worker/tests/test_runner.py`
- Modify: `worker/src/main.py`

- [ ] **Step 1: Copy db.py from orchestrator**

```bash
cp orchestrator/src/db.py worker/src/db.py
```

- [ ] **Step 2: Write failing test for job runner**

```python
# worker/tests/test_runner.py
from src.db import init_db, get_connection
from src.jobs.runner import pick_next_job, mark_job_running, mark_job_completed, mark_job_failed

def test_pick_next_job_returns_oldest_queued(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'queued')")
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j2', 'simmer_domain', 'techniques', 'queued')")
    conn.commit()

    job = pick_next_job(conn)
    assert job is not None
    assert job["id"] == "j1"
    conn.close()

def test_pick_next_job_skips_running(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'running')")
    conn.commit()

    job = pick_next_job(conn)
    assert job is None
    conn.close()

def test_mark_job_running(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'queued')")
    conn.commit()

    mark_job_running(conn, "j1")
    row = conn.execute("SELECT status, started_at FROM jobs WHERE id = 'j1'").fetchone()
    assert row[0] == "running"
    assert row[1] is not None
    conn.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd worker && pip install -e ".[dev]" && python -m pytest tests/test_runner.py -v`
Expected: FAIL

- [ ] **Step 4: Implement job runner**

```python
# worker/src/jobs/runner.py
import sqlite3
from datetime import datetime, timezone

def pick_next_job(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT id, type, target, config FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return {"id": row[0], "type": row[1], "target": row[2], "config": row[3]}

def mark_job_running(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), job_id),
    )
    conn.commit()

def mark_job_completed(conn: sqlite3.Connection, job_id: str, result: str = "") -> None:
    conn.execute(
        "UPDATE jobs SET status = 'completed', completed_at = ?, result = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), result, job_id),
    )
    conn.commit()

def mark_job_failed(conn: sqlite3.Connection, job_id: str, error: str = "") -> None:
    conn.execute(
        "UPDATE jobs SET status = 'failed', completed_at = ?, result = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), error, job_id),
    )
    conn.commit()
```

- [ ] **Step 5: Update worker main.py with job dispatch**

```python
# worker/src/main.py
import asyncio
import json
import traceback
from .config import get_settings
from .db import init_db, get_connection
from .jobs.runner import pick_next_job, mark_job_running, mark_job_completed, mark_job_failed

async def handle_job(job: dict, db_path: str) -> None:
    """Dispatch job to appropriate handler."""
    if job["type"] == "simmer_general":
        from .jobs.simmer_general import run_simmer_general
        await run_simmer_general(job, db_path)
    elif job["type"] == "simmer_domain":
        from .jobs.simmer_domain import run_simmer_domain
        await run_simmer_domain(job, db_path)
    elif job["type"] == "extract_batch":
        from .jobs.extract_batch import run_extract_batch
        await run_extract_batch(job, db_path)
    else:
        raise ValueError(f"Unknown job type: {job['type']}")

async def poll_loop():
    settings = get_settings()
    init_db(settings.db_path)
    print(f"Worker started, polling every {settings.worker_poll_interval}s", flush=True)

    while True:
        conn = get_connection(settings.db_path)
        job = pick_next_job(conn)

        if job:
            print(f"Picked up job {job['id']} ({job['type']})", flush=True)
            mark_job_running(conn, job["id"])
            conn.close()

            try:
                await handle_job(job, settings.db_path)
                conn = get_connection(settings.db_path)
                mark_job_completed(conn, job["id"])
                print(f"Job {job['id']} completed", flush=True)
            except Exception as e:
                conn = get_connection(settings.db_path)
                mark_job_failed(conn, job["id"], traceback.format_exc())
                print(f"Job {job['id']} failed: {e}", flush=True)
            finally:
                conn.close()
        else:
            conn.close()

        await asyncio.sleep(settings.worker_poll_interval)

def main():
    asyncio.run(poll_loop())

if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests**

Run: `cd worker && python -m pytest tests/test_runner.py -v`
Expected: 3 PASSED

- [ ] **Step 7: Commit**

```bash
git add worker/
git commit -m "feat: simmer worker with job runner, polling loop, and dispatch"
```

---

## Task 12: Simmer Worker — General Spec Job

**Files:**
- Create: `worker/src/jobs/simmer_general.py`
- Create: `worker/src/jobs/extract_batch.py`
- Create: `worker/src/jobs/simmer_domain.py` (stub)
- Create: `worker/src/evaluators/score_golden_set.py`
- Create: `worker/src/evaluators/eval_runner_haiku.py`
- Create: `worker/src/evaluators/eval_scorer.py`
- Create: `worker/tests/test_simmer_general.py`

- [ ] **Step 1: Write failing test**

```python
# worker/tests/test_simmer_general.py
from unittest.mock import AsyncMock, patch, MagicMock
from src.db import init_db, get_connection

async def test_simmer_general_creates_spec(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    # Insert sample documents
    for i in range(3):
        conn.execute(
            "INSERT INTO documents (id, title, content, status) VALUES (?, ?, ?, 'classified')",
            (f"d{i}", f"Doc {i}", f"Content about topic {i}"),
        )
    conn.commit()
    conn.close()

    mock_result = MagicMock()
    mock_result.best_candidate = "Extract Person, Thing, Topic from text..."
    mock_result.composite = 7.5
    mock_result.best_scores = {"coverage": 8, "precision": 7}

    with patch("src.jobs.simmer_general.refine", new_callable=AsyncMock, return_value=mock_result):
        from src.jobs.simmer_general import run_simmer_general
        await run_simmer_general({"id": "j1", "type": "simmer_general", "target": "general", "config": None}, db_path)

    conn = get_connection(db_path)
    spec = conn.execute("SELECT * FROM specs WHERE domain_path IS NULL").fetchone()
    assert spec is not None
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker && python -m pytest tests/test_simmer_general.py -v`
Expected: FAIL

- [ ] **Step 3: Implement simmer_general job**

```python
# worker/src/jobs/simmer_general.py
import uuid
import json
from pathlib import Path
from simmer_sdk import refine
from ..db import get_connection
from ..config import get_settings

SEED_ONTOLOGY = """Entity types to extract:
- Person — people, speakers, authors, creators
- Organization — companies, groups, teams, brands
- Topic — concepts, ideas, theories, fields, subjects
- Event — happenings, milestones, dates, releases
- Location — places, regions, settings, venues
- Thing — objects, tools, products, materials, artifacts

For each entity found in the text, output:
{"name": "entity name", "type": "EntityType"}

Rules:
- Only extract entities explicitly mentioned in the text
- Normalize names to lowercase
- Do not hallucinate entities not present in the source
"""

async def run_simmer_general(job: dict, db_path: str) -> None:
    settings = get_settings()
    conn = get_connection(db_path)

    # 1. Gather diverse sample documents
    docs = conn.execute(
        "SELECT id, title, content FROM documents WHERE status IN ('classified', 'extracted') ORDER BY RANDOM() LIMIT 10"
    ).fetchall()

    if not docs:
        conn.close()
        raise ValueError("No documents available to simmer general spec")

    # Write sample docs to temp files for evaluator
    specs_dir = Path(settings.specs_dir)
    specs_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = specs_dir / "general_samples"
    sample_dir.mkdir(exist_ok=True)

    for doc in docs:
        (sample_dir / f"{doc[0]}.txt").write_text(doc[2])

    # Write seed spec as starting artifact
    seed_path = specs_dir / "general_seed.md"
    seed_path.write_text(SEED_ONTOLOGY)

    conn.close()

    # 2. Phase 1: Golden set simmering
    golden_result = await refine(
        artifact=str(seed_path),
        criteria={
            "coverage": "Captures all entity types present in sample documents — people, things, concepts, everything a reader would want indexed",
            "precision": "No hallucinated entities, no noise — every entity in the golden set is actually in the source text",
            "taxonomy_quality": "Entity types are meaningful, consistent, and cover the domain without overlap or gaps",
        },
        primary="coverage",
        evaluator=f"python -c \"import json; print(json.dumps({{'entities': 'evaluated'}}))\"\n",
        iterations=settings.simmer_iterations,
        judge_mode="board",
        output_dir=specs_dir / "general_golden",
        generator_model="claude-sonnet-4-20250514",
        judge_model="claude-sonnet-4-20250514",
        background=f"Sample documents are in {sample_dir}. Read them to understand what entity types exist in this corpus.",
    )

    # 3. Phase 2: Extraction spec simmering
    spec_result = await refine(
        artifact=golden_result.best_candidate,
        criteria={
            "coverage": "When run on sample docs, the spec finds all entities from the golden set",
            "precision": "Zero false positives — no extracted entities that aren't in the source text",
            "format_compliance": "Output is valid JSON with name and type fields for every entity",
        },
        primary="coverage",
        iterations=settings.simmer_iterations,
        judge_mode="board",
        output_dir=specs_dir / "general_spec",
        generator_model="claude-sonnet-4-20250514",
        judge_model="claude-sonnet-4-20250514",
        clerk_model="claude-haiku-4-20250514",
        background=f"This spec will be executed by Haiku on document chunks. It must be clear and explicit enough for a smaller model to follow precisely. Golden set: {golden_result.best_candidate[:2000]}",
    )

    # 4. Store spec
    conn = get_connection(db_path)
    spec_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content, golden_set, score) VALUES (?, NULL, 1, ?, ?, ?)",
        (spec_id, spec_result.best_candidate, golden_result.best_candidate, spec_result.composite),
    )

    # 5. Queue batch extraction for all classified docs
    job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch', 'general', 'queued', ?)",
        (job_id, json.dumps({"spec_id": spec_id, "scope": "all_classified"})),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 4: Implement extract_batch job**

```python
# worker/src/jobs/extract_batch.py
import json
import uuid
from anthropic import AsyncAnthropic
from ..db import get_connection
from ..config import get_settings

async def run_extract_batch(job: dict, db_path: str) -> None:
    settings = get_settings()
    conn = get_connection(db_path)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    config = json.loads(job["config"]) if job["config"] else {}
    spec_id = config.get("spec_id")
    scope = config.get("scope", "all_classified")

    # Get the spec
    spec_row = conn.execute("SELECT spec_content FROM specs WHERE id = ?", (spec_id,)).fetchone()
    if not spec_row:
        conn.close()
        raise ValueError(f"Spec not found: {spec_id}")
    spec = spec_row[0]

    # Get target documents
    if scope == "all_classified":
        docs = conn.execute(
            "SELECT id FROM documents WHERE status = 'classified'"
        ).fetchall()
    else:
        domain = config.get("domain")
        docs = conn.execute(
            """SELECT d.id FROM documents d
               JOIN document_domains dd ON d.id = dd.document_id
               WHERE dd.domain_path = ?""",
            (domain,),
        ).fetchall()

    conn.close()

    # Import extraction logic (same as orchestrator — consider shared package later)
    # For now, inline the extraction call
    for doc_row in docs:
        doc_id = doc_row[0]
        conn = get_connection(db_path)

        chunks = conn.execute(
            "SELECT id, text FROM chunks WHERE document_id = ? ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()

        chunk_entities: dict[str, list[str]] = {}

        for chunk in chunks:
            chunk_id, chunk_text = chunk[0], chunk[1]

            response = await client.messages.create(
                model=settings.extraction_model,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": f"{spec}\n\nTEXT:\n{chunk_text}\n\nRespond with JSON only: {{\"entities\": [{{\"name\": \"...\", \"type\": \"...\"}}]}}",
                }],
            )

            text = response.content[0].text
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]

            try:
                result = json.loads(text)
                entities = result.get("entities", [])
            except json.JSONDecodeError:
                continue

            for entity in entities:
                name = entity.get("name", "").lower().strip()
                etype = entity.get("type", "Thing")
                if not name:
                    continue

                # Check merge map
                row = conn.execute("SELECT to_entity_id FROM merge_map WHERE from_name = ?", (name,)).fetchone()
                if row:
                    entity_id = row[0]
                else:
                    row = conn.execute("SELECT id FROM entities WHERE canonical_name = ? AND type = ?", (name, etype)).fetchone()
                    if row:
                        entity_id = row[0]
                    else:
                        entity_id = str(uuid.uuid4())
                        conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, ?)", (entity_id, name, etype))

                conn.execute(
                    "INSERT INTO entity_sources (entity_id, document_id, chunk_id, extraction_pass) VALUES (?, ?, ?, 'general')",
                    (entity_id, doc_id, chunk_id),
                )
                chunk_entities.setdefault(chunk_id, []).append(entity_id)

        # Co-occurrence edges
        from itertools import combinations
        pair_counts: dict[tuple, int] = {}
        for cid, eids in chunk_entities.items():
            for a, b in combinations(sorted(set(eids)), 2):
                pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1

        for (a, b), weight in pair_counts.items():
            conn.execute(
                "INSERT INTO relationships (id, from_entity, to_entity, type, weight) VALUES (?, ?, ?, 'co_occurs', ?)",
                (str(uuid.uuid4()), a, b, weight),
            )

        conn.execute("UPDATE documents SET status = 'extracted' WHERE id = ?", (doc_id,))
        conn.commit()
        conn.close()
```

- [ ] **Step 5: Create stub for simmer_domain**

```python
# worker/src/jobs/simmer_domain.py
import json
from ..db import get_connection

async def run_simmer_domain(job: dict, db_path: str) -> None:
    """Domain-specific spec simmering — same two-phase pattern as general,
    scoped to one domain. Starts from general spec entity types.

    Not yet implemented. Marks the job as failed with a descriptive message
    so the user knows this feature is pending.
    """
    conn = get_connection(db_path)
    conn.execute(
        "UPDATE jobs SET status = 'failed', result = ? WHERE id = ?",
        (json.dumps({"error": "Domain-specific simmering not yet implemented. Use general spec simmering for now."}), job["id"]),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 6: Run test**

Run: `cd worker && python -m pytest tests/test_simmer_general.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add worker/
git commit -m "feat: simmer worker jobs — general spec simmering, batch extraction, domain stub"
```

---

## Task 13: Frontend Scaffolding

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/next.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/src/app/layout.tsx`
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/types.ts`

- [ ] **Step 1: Initialize Next.js project**

Run from project root:
```bash
cd frontend && npx create-next-app@latest . --typescript --tailwind --eslint --app --src-dir --no-import-alias --use-npm
```

- [ ] **Step 2: Install shadcn/ui**

```bash
cd frontend && npx shadcn@latest init -d
```

- [ ] **Step 3: Install shadcn components we need**

```bash
cd frontend && npx shadcn@latest add button card table badge tabs input
```

- [ ] **Step 4: Create `frontend/src/lib/types.ts`**

```typescript
// frontend/src/lib/types.ts
export interface DocumentSummary {
  id: string;
  title: string;
  status: "pending" | "classified" | "extracted" | "enriched";
  created_at: string;
  domains: string[];
  entity_count: number;
}

export interface DomainInfo {
  id: string;
  path: string;
  parent_path: string | null;
  document_count: number;
  spec_version: number | null;
  created_at: string;
}

export interface EntitySummary {
  id: string;
  canonical_name: string;
  type: string;
  source_count: number;
}

export interface JobInfo {
  id: string;
  type: string;
  target: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface Stats {
  document_count: number;
  entity_count: number;
  domain_count: number;
  active_jobs: number;
}

export interface IngestResult {
  document_id: string;
  title: string;
  domains: string[];
  entity_count: number;
  jobs_queued: string[];
}
```

- [ ] **Step 5: Create `frontend/src/lib/api.ts`**

```typescript
// frontend/src/lib/api.ts
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, options);
  if (!res.ok) throw new Error(`API error: ${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  getStats: () => fetchAPI<import("./types").Stats>("/stats"),
  getDocuments: () => fetchAPI<import("./types").DocumentSummary[]>("/documents"),
  getDomains: () => fetchAPI<import("./types").DomainInfo[]>("/domains"),
  getEntities: (params?: { type?: string; domain?: string }) => {
    const query = new URLSearchParams();
    if (params?.type) query.set("type", params.type);
    if (params?.domain) query.set("domain", params.domain);
    return fetchAPI<import("./types").EntitySummary[]>(`/entities?${query}`);
  },
  getJobs: () => fetchAPI<import("./types").JobInfo[]>("/jobs"),
  ingestFile: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetchAPI<import("./types").IngestResult>("/ingest", { method: "POST", body: form });
  },
  ingestDirectory: (path: string) =>
    fetchAPI<{ documents: import("./types").IngestResult[]; total: number }>("/ingest/directory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  triggerGeneralSimmer: () =>
    fetchAPI<{ job_id: string }>("/simmer/general", { method: "POST" }),
  triggerDomainSimmer: (domain: string) =>
    fetchAPI<{ job_id: string }>(`/simmer/${domain}`, { method: "POST" }),
};
```

- [ ] **Step 6: Update `frontend/src/app/layout.tsx`** with nav

```tsx
// frontend/src/app/layout.tsx
import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Noospheric Orrery",
  description: "Adaptive knowledge graph extraction pipeline",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background">
        <nav className="border-b px-6 py-3 flex gap-6 items-center">
          <span className="font-semibold text-lg">Noospheric Orrery</span>
          <Link href="/" className="text-sm hover:underline">Upload</Link>
          <Link href="/pipeline" className="text-sm hover:underline">Pipeline</Link>
          <Link href="/entities" className="text-sm hover:underline">Entities</Link>
        </nav>
        <main className="p-6">{children}</main>
      </body>
    </html>
  );
}
```

- [ ] **Step 7: Verify frontend builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "feat: Next.js frontend scaffold with shadcn/ui, API client, and nav layout"
```

---

## Task 14: Upload Page

**Files:**
- Create: `frontend/src/components/file-upload.tsx`
- Create: `frontend/src/components/upload-status.tsx`
- Modify: `frontend/src/app/page.tsx`

- [ ] **Step 1: Create file upload component**

```tsx
// frontend/src/components/file-upload.tsx
"use client";

import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { IngestResult } from "@/lib/types";

interface FileUploadProps {
  onResult: (result: IngestResult) => void;
  onError: (error: string) => void;
}

export function FileUpload({ onResult, onError }: FileUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [dirPath, setDirPath] = useState("");

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files) return;
    setUploading(true);
    for (const file of Array.from(files)) {
      try {
        const result = await api.ingestFile(file);
        onResult(result);
      } catch (e) {
        onError(`Failed to ingest ${file.name}: ${e}`);
      }
    }
    setUploading(false);
  }, [onResult, onError]);

  const handleDirectory = useCallback(async () => {
    if (!dirPath.trim()) return;
    setUploading(true);
    try {
      const result = await api.ingestDirectory(dirPath.trim());
      result.documents.forEach(onResult);
    } catch (e) {
      onError(`Failed to ingest directory: ${e}`);
    }
    setUploading(false);
  }, [dirPath, onResult, onError]);

  return (
    <div className="space-y-6">
      <div
        className="border-2 border-dashed rounded-lg p-12 text-center cursor-pointer hover:border-primary transition-colors"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files); }}
        onClick={() => document.getElementById("file-input")?.click()}
      >
        <p className="text-muted-foreground">
          {uploading ? "Uploading..." : "Drop files here or click to browse"}
        </p>
        <p className="text-xs text-muted-foreground mt-2">.txt, .md, .json, .csv</p>
        <input
          id="file-input"
          type="file"
          multiple
          accept=".txt,.md,.json,.csv"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      <div className="flex gap-2">
        <Input
          placeholder="Or paste a directory path..."
          value={dirPath}
          onChange={(e) => setDirPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleDirectory()}
        />
        <Button onClick={handleDirectory} disabled={uploading || !dirPath.trim()}>
          Ingest
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create upload status component**

```tsx
// frontend/src/components/upload-status.tsx
"use client";

import { Badge } from "@/components/ui/badge";
import { IngestResult } from "@/lib/types";

interface UploadStatusProps {
  results: IngestResult[];
  errors: string[];
}

export function UploadStatus({ results, errors }: UploadStatusProps) {
  if (results.length === 0 && errors.length === 0) return null;

  const totalEntities = results.reduce((sum, r) => sum + r.entity_count, 0);
  const allDomains = [...new Set(results.flatMap((r) => r.domains))];
  const hasJobs = results.some((r) => r.jobs_queued.length > 0);

  return (
    <div className="space-y-4">
      {results.length > 0 && (
        <div className="rounded-lg border p-4">
          <p className="font-medium">
            {results.length} file{results.length !== 1 ? "s" : ""} uploaded
            {allDomains.length > 0 && `, ${allDomains.length} domain${allDomains.length !== 1 ? "s" : ""} detected`}
            {totalEntities > 0 && `, ${totalEntities} entities extracted`}
          </p>
          {hasJobs && (
            <p className="text-sm text-muted-foreground mt-1">
              Simmering job queued — check <a href="/pipeline" className="underline">Pipeline</a> for progress
            </p>
          )}
          <div className="mt-3 space-y-1">
            {results.map((r) => (
              <div key={r.document_id} className="flex items-center gap-2 text-sm">
                <Badge variant={r.entity_count > 0 ? "default" : "secondary"}>
                  {r.entity_count > 0 ? "extracted" : "classified"}
                </Badge>
                <span>{r.title}</span>
                <span className="text-muted-foreground">→ {r.domains.join(", ") || "no domain"}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {errors.map((err, i) => (
        <div key={i} className="rounded-lg border border-destructive p-4 text-sm text-destructive">{err}</div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Wire up the upload page**

```tsx
// frontend/src/app/page.tsx
"use client";

import { useState } from "react";
import { FileUpload } from "@/components/file-upload";
import { UploadStatus } from "@/components/upload-status";
import { IngestResult } from "@/lib/types";

export default function UploadPage() {
  const [results, setResults] = useState<IngestResult[]>([]);
  const [errors, setErrors] = useState<string[]>([]);

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Upload Documents</h1>
        <p className="text-muted-foreground mt-1">
          Upload text files or point at a directory to start building the knowledge graph.
        </p>
      </div>
      <FileUpload
        onResult={(r) => setResults((prev) => [...prev, r])}
        onError={(e) => setErrors((prev) => [...prev, e])}
      />
      <UploadStatus results={results} errors={errors} />
    </div>
  );
}
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat: upload page with drag-and-drop, directory ingest, and status display"
```

---

## Task 15: Pipeline Page

**Files:**
- Create: `frontend/src/components/stats-bar.tsx`
- Create: `frontend/src/components/domain-tree.tsx`
- Create: `frontend/src/components/jobs-table.tsx`
- Create: `frontend/src/app/pipeline/page.tsx`

- [ ] **Step 1: Create stats bar component**

```tsx
// frontend/src/components/stats-bar.tsx
"use client";

import { Card } from "@/components/ui/card";
import { Stats } from "@/lib/types";

export function StatsBar({ stats }: { stats: Stats | null }) {
  if (!stats) return <div className="text-muted-foreground">Loading...</div>;
  const items = [
    { label: "Documents", value: stats.document_count },
    { label: "Entities", value: stats.entity_count },
    { label: "Domains", value: stats.domain_count },
    { label: "Active Jobs", value: stats.active_jobs },
  ];
  return (
    <div className="grid grid-cols-4 gap-4">
      {items.map((item) => (
        <Card key={item.label} className="p-4 text-center">
          <p className="text-2xl font-bold">{item.value}</p>
          <p className="text-sm text-muted-foreground">{item.label}</p>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create domain tree component**

```tsx
// frontend/src/components/domain-tree.tsx
"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DomainInfo } from "@/lib/types";
import { api } from "@/lib/api";

export function DomainTree({ domains }: { domains: DomainInfo[] }) {
  if (domains.length === 0) return <p className="text-muted-foreground">No domains yet</p>;

  const handleSimmer = async (path: string) => {
    try {
      await api.triggerDomainSimmer(path);
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="space-y-1">
      {domains.map((d) => (
        <div key={d.id} className="flex items-center gap-3 py-1 px-2 rounded hover:bg-muted">
          <span className="font-mono text-sm flex-1">{d.path}</span>
          <span className="text-sm text-muted-foreground">{d.document_count} docs</span>
          <Badge variant={d.spec_version ? "default" : "outline"}>
            {d.spec_version ? `v${d.spec_version}` : "no spec"}
          </Badge>
          {!d.spec_version && (
            <Button size="sm" variant="outline" onClick={() => handleSimmer(d.path)}>
              Simmer
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Create jobs table component**

```tsx
// frontend/src/components/jobs-table.tsx
"use client";

import { Badge } from "@/components/ui/badge";
import { JobInfo } from "@/lib/types";

const statusColors: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  queued: "outline",
  running: "secondary",
  completed: "default",
  failed: "destructive",
};

export function JobsTable({ jobs }: { jobs: JobInfo[] }) {
  if (jobs.length === 0) return <p className="text-muted-foreground">No jobs</p>;

  return (
    <div className="space-y-1">
      {jobs.map((j) => (
        <div key={j.id} className="flex items-center gap-3 py-1 px-2 rounded hover:bg-muted text-sm">
          <Badge variant={statusColors[j.status] || "outline"}>{j.status}</Badge>
          <span className="font-mono">{j.type}</span>
          <span className="text-muted-foreground">{j.target}</span>
          <span className="text-muted-foreground ml-auto">{new Date(j.created_at).toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Wire up the pipeline page**

```tsx
// frontend/src/app/pipeline/page.tsx
"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { StatsBar } from "@/components/stats-bar";
import { DomainTree } from "@/components/domain-tree";
import { JobsTable } from "@/components/jobs-table";
import { api } from "@/lib/api";
import type { Stats, DomainInfo, JobInfo } from "@/lib/types";

export default function PipelinePage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [domains, setDomains] = useState<DomainInfo[]>([]);
  const [jobs, setJobs] = useState<JobInfo[]>([]);

  const refresh = async () => {
    const [s, d, j] = await Promise.all([api.getStats(), api.getDomains(), api.getJobs()]);
    setStats(s);
    setDomains(d);
    setJobs(j);
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleGeneralSimmer = async () => {
    try {
      await api.triggerGeneralSimmer();
      refresh();
    } catch (e) {
      console.error(e);
    }
  };

  const hasGeneralSpec = stats && stats.entity_count > 0; // rough proxy

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Pipeline</h1>
      <StatsBar stats={stats} />

      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium">Domains</h2>
          {!hasGeneralSpec && (
            <Button onClick={handleGeneralSimmer}>Simmer General Spec</Button>
          )}
        </div>
        <DomainTree domains={domains} />
      </section>

      <section>
        <h2 className="text-lg font-medium mb-4">Jobs</h2>
        <JobsTable jobs={jobs} />
      </section>
    </div>
  );
}
```

- [ ] **Step 5: Verify build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat: pipeline page with stats, domain tree, jobs table, and simmer triggers"
```

---

## Task 16: Entities Page

**Files:**
- Create: `frontend/src/components/entity-table.tsx`
- Create: `frontend/src/app/entities/page.tsx`

- [ ] **Step 1: Create entity table component**

```tsx
// frontend/src/components/entity-table.tsx
"use client";

import { Badge } from "@/components/ui/badge";
import { EntitySummary } from "@/lib/types";

export function EntityTable({ entities }: { entities: EntitySummary[] }) {
  if (entities.length === 0) return <p className="text-muted-foreground">No entities yet</p>;

  return (
    <div className="rounded-md border">
      <div className="grid grid-cols-4 gap-4 p-3 border-b font-medium text-sm">
        <span>Name</span>
        <span>Type</span>
        <span>Sources</span>
        <span></span>
      </div>
      {entities.map((e) => (
        <div key={e.id} className="grid grid-cols-4 gap-4 p-3 border-b last:border-0 text-sm hover:bg-muted">
          <span className="font-medium">{e.canonical_name}</span>
          <Badge variant="outline">{e.type}</Badge>
          <span className="text-muted-foreground">{e.source_count} docs</span>
          <a href={`/entities/${e.id}`} className="text-primary hover:underline">detail</a>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Wire up entities page**

```tsx
// frontend/src/app/entities/page.tsx
"use client";

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { EntityTable } from "@/components/entity-table";
import { api } from "@/lib/api";
import type { EntitySummary } from "@/lib/types";

export default function EntitiesPage() {
  const [entities, setEntities] = useState<EntitySummary[]>([]);
  const [typeFilter, setTypeFilter] = useState("");

  useEffect(() => {
    api.getEntities(typeFilter ? { type: typeFilter } : undefined).then(setEntities);
  }, [typeFilter]);

  const types = [...new Set(entities.map((e) => e.type))].sort();

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Entities</h1>
      <div className="flex gap-4">
        <select
          className="border rounded px-3 py-2 text-sm"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        >
          <option value="">All types</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <EntityTable entities={entities} />
    </div>
  );
}
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: entities page with type filtering and entity table"
```

---

## Task 17: Docker Integration Test

**Files:**
- None new — verify existing containers work together

- [ ] **Step 1: Create `.env` from example**

```bash
cp .env.example .env
# Edit .env with your actual ANTHROPIC_API_KEY
```

- [ ] **Step 2: Build and start all containers**

Run: `docker compose build && docker compose up -d`
Expected: All 3 containers start without errors

- [ ] **Step 3: Verify health endpoint**

Run: `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`

- [ ] **Step 4: Verify frontend loads**

Open: `http://localhost:3000`
Expected: Upload page renders with drag-and-drop zone and nav bar

- [ ] **Step 5: Verify stats endpoint**

Run: `curl http://localhost:8000/stats`
Expected: `{"document_count":0,"entity_count":0,"domain_count":0,"active_jobs":0}`

- [ ] **Step 6: Test ingest with a sample file**

```bash
echo "This is a test document about painting miniatures with wet blending techniques. Duncan Rhodes demonstrates the process." > /tmp/test-doc.txt
curl -X POST http://localhost:8000/ingest -F "file=@/tmp/test-doc.txt"
```
Expected: JSON response with document_id, domains, and jobs_queued

- [ ] **Step 7: Verify document appears in API**

Run: `curl http://localhost:8000/documents`
Expected: List with 1 document, status "classified"

- [ ] **Step 8: Check worker logs for job pickup**

Run: `docker compose logs worker`
Expected: "Picked up job ... (simmer_general)" if a simmer job was queued

- [ ] **Step 9: Commit any docker fixes**

```bash
git add docker-compose.yml orchestrator/Dockerfile worker/Dockerfile frontend/Dockerfile
git commit -m "fix: docker compose integration verified end-to-end"
```

---

## Summary

| Task | What It Builds | Depends On |
|------|---------------|------------|
| 1 | Project scaffolding + Docker Compose | — |
| 2 | SQLite database layer | 1 |
| 3 | Document chunking + classification excerpts | 1 |
| 4 | Pydantic models | 1 |
| 5 | Sonnet domain classification | 3 |
| 6 | Domain normalization | 2, 5 |
| 7 | Haiku entity extraction | 3 |
| 8 | Entity normalization + co-occurrence | 2, 7 |
| 9 | Ingest route (pipeline wiring) | 2-8 |
| 10 | Read-only API routes | 2, 4 |
| 11 | Simmer worker — job runner | 2 |
| 12 | Simmer worker — general spec job | 11 |
| 13 | Frontend scaffolding | 1 |
| 14 | Upload page | 13 |
| 15 | Pipeline page | 13 |
| 16 | Entities page | 13 |
| 17 | Docker integration test | All |

**Parallelizable:** Tasks 3-8 (backend pipeline modules) can be built in parallel. Tasks 13-16 (frontend) can be built in parallel with tasks 9-12 (backend routes + worker).

---

## Known Deferred Items

These are acknowledged gaps that should be addressed after the end-to-end pipeline is working:

1. **Embedding-based normalization for domains and entities.** Tasks 6 and 8 implement merge-map + exact match normalization only. The spec's full cascade (embed → cosine compare → LLM review for ambiguous cases) should be added once the pipeline runs end-to-end. This requires `sentence-transformers` + `all-MiniLM-L6-v2` loaded in both orchestrator and worker containers.

2. **Domain-specific simmering (`simmer_domain`).** The worker has a stub that fails gracefully. Implement after general spec simmering is validated. Same two-phase pattern (golden set → extraction spec) scoped to one domain.

3. **Evaluator scripts.** The simmer_general job uses a placeholder evaluator. Real evaluators (`score_golden_set.py`, `eval_runner_haiku.py`, `eval_scorer.py`) should be ported from the extraction pipeline experiments once simmer-sdk integration is tested.

4. **`mentions` relationship type.** The spec defines it as V1 but it's derivable from `entity_sources` and doesn't need explicit rows for the dashboard to work. Add if Phase B visualization needs it.

5. **Frontend tests.** No frontend tests in this plan. Add when the UI stabilizes.
