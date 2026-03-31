# Google Embeddings + Firestore Vector Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace sentence-transformers with Google Vertex AI embeddings, replace FAISS with Firestore vector search, and re-fit UMAP on Google embeddings for the cloud deployment.

**Architecture:** A thin embedding client calls Vertex AI's `text-embedding-004` model. Embeddings are stored as Firestore vector fields on entity/chunk documents. Search uses Firestore `find_nearest()` instead of FAISS. UMAP is re-fit on Google embeddings from our 30+ local domains, then pushed to Firestore. New domains use `transform()`.

**Tech Stack:** Vertex AI Embeddings API (`google-cloud-aiplatform`), Firestore vector search (`find_nearest`), UMAP (`umap-learn`), Python 3.13+

---

## File Structure

### New files
- `orchestrator/src/services/embedding.py` — Vertex AI embedding client (replaces local sentence-transformers)
- `orchestrator/scripts/fit_umap_google.py` — One-time script: embed domains via Vertex AI → fit UMAP → push to Firestore
- `orchestrator/scripts/backfill_embeddings.py` — One-time script: embed all existing entities/chunks → store as vector fields
- `orchestrator/scripts/create_vector_indexes.sh` — gcloud commands to create Firestore vector indexes

### Modified files
- `orchestrator/src/pipeline/domain_layout.py` — Replace sentence-transformers calls with Vertex AI client
- `orchestrator/src/pipeline/search/retrieval.py` — Replace FAISS with Firestore `find_nearest()`
- `orchestrator/src/pipeline/search/pipeline.py` — Wire new retrieval into search pipeline
- `orchestrator/src/pipeline/embedding_normalizer.py` — Replace sentence-transformers with Vertex AI for similarity
- `orchestrator/src/routes/search.py` — Remove FAISS/SQLite branch, use Firestore vector search on all backends
- `orchestrator/src/routes/graph.py` — Remove SQLite-only UMAP branch
- `orchestrator/src/routes/ingest.py` — Embed entities/chunks after extraction
- `orchestrator/src/repositories/firestore_store.py` — Store embeddings as Firestore Vector type
- `orchestrator/pyproject.toml` — Add `google-cloud-aiplatform`, keep `umap-learn`, remove `faiss-cpu` and `sentence-transformers`
- `orchestrator/Dockerfile` — Remove sentence-transformers (no model baking needed)

---

## Task 1: Vertex AI Embedding Client

**Files:**
- Create: `orchestrator/src/services/__init__.py`
- Create: `orchestrator/src/services/embedding.py`
- Test: `orchestrator/tests/test_embedding_service.py`

- [ ] **Step 1: Create the embedding service module**

```python
# orchestrator/src/services/__init__.py
# empty

# orchestrator/src/services/embedding.py
"""Vertex AI embedding client.

Calls Google's text-embedding-004 model via the Vertex AI API.
Replaces local sentence-transformers for all embedding operations.
"""
from __future__ import annotations
import os
from functools import lru_cache

def _get_model():
    """Lazy-load the Vertex AI TextEmbeddingModel."""
    from vertexai.language_models import TextEmbeddingModel
    import vertexai
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "noospheric-orrery")
    region = os.environ.get("VERTEX_AI_REGION", "us-central1")
    vertexai.init(project=project_id, location=region)
    return TextEmbeddingModel.from_pretrained("text-embedding-004")

_model = None

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using Vertex AI text-embedding-004.

    Returns list of embedding vectors (768 dimensions for text-embedding-004).
    """
    global _model
    if _model is None:
        _model = _get_model()

    # Vertex AI accepts batches of up to 250 texts
    all_embeddings = []
    for i in range(0, len(texts), 250):
        batch = texts[i:i+250]
        embeddings = _model.get_embeddings(batch)
        all_embeddings.extend([e.values for e in embeddings])
    return all_embeddings


def embed_text(text: str) -> list[float]:
    """Embed a single text."""
    return embed_texts([text])[0]


def get_embedding_dimension() -> int:
    """Return the dimensionality of the embedding model."""
    return 768  # text-embedding-004 produces 768-dim vectors
```

- [ ] **Step 2: Write a basic test**

```python
# orchestrator/tests/test_embedding_service.py
"""Test the Vertex AI embedding client.

Requires GOOGLE_APPLICATION_CREDENTIALS to be set.
Skip in CI without credentials.
"""
import os
import pytest

# Skip if no GCP credentials
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
    reason="No GCP credentials"
)

def test_embed_single_text():
    from src.services.embedding import embed_text, get_embedding_dimension
    vec = embed_text("hello world")
    assert len(vec) == get_embedding_dimension()
    assert all(isinstance(v, float) for v in vec)

def test_embed_batch():
    from src.services.embedding import embed_texts
    vecs = embed_texts(["hello", "world", "test"])
    assert len(vecs) == 3
    assert all(len(v) == 768 for v in vecs)
```

- [ ] **Step 3: Run test to verify it works**

```bash
cd orchestrator
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json \
  .venv/bin/pytest tests/test_embedding_service.py -v
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/services/ orchestrator/tests/test_embedding_service.py
git commit -m "feat: Vertex AI embedding client (text-embedding-004)"
```

---

## Task 2: Fit UMAP on Google Embeddings

**Files:**
- Create: `orchestrator/scripts/fit_umap_google.py`

- [ ] **Step 1: Write the UMAP fitting script**

This script:
1. Reads all 30+ domains from local SQLite
2. Builds domain text (path + titles + entities) for each
3. Embeds via Vertex AI
4. Fits UMAP on the embeddings
5. Pushes positions + fitted model to Firestore

```python
# orchestrator/scripts/fit_umap_google.py
"""One-time script: fit UMAP on Google embeddings for all local domains.

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json \
    python scripts/fit_umap_google.py

Reads domains from local SQLite, embeds via Vertex AI, fits UMAP,
pushes positions + model to Firestore.
"""
import os
import sys
import pickle
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sqlite3
import umap
from src.services.embedding import embed_texts
from src.repositories.firestore_store import FirestoreDataStore

DB_PATH = os.environ.get("DB_PATH", os.path.expanduser("~/orrery-data/orrery.db"))
PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "noospheric-orrery")
WORKSPACE_ID = os.environ.get("FIREBASE_WORKSPACE_ID", "default")

def build_domain_text(conn, path):
    titles = conn.execute("""
        SELECT d.title FROM documents d
        JOIN document_domains dd ON d.id = dd.document_id
        WHERE dd.domain_path = ? ORDER BY d.created_at DESC LIMIT 6
    """, (path,)).fetchall()
    entities = conn.execute("""
        SELECT e.canonical_name FROM entities e
        JOIN entity_sources es ON e.id = es.entity_id
        JOIN document_domains dd ON es.document_id = dd.document_id
        WHERE dd.domain_path = ? GROUP BY e.id ORDER BY COUNT(*) DESC LIMIT 12
    """, (path,)).fetchall()
    return f"{path.replace('/', ' ')}. {' '.join(r[0] for r in titles if r[0])}. {' '.join(r[0] for r in entities)}"

def main():
    # Read domains from local SQLite
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    domains = conn.execute("SELECT path FROM domains WHERE document_count > 0 ORDER BY path").fetchall()
    paths = [r["path"] for r in domains]
    print(f"Found {len(paths)} domains")

    # Build texts and embed via Vertex AI
    texts = [build_domain_text(conn, p) for p in paths]
    print(f"Embedding {len(texts)} domain texts via Vertex AI...")
    embeddings = embed_texts(texts)
    embeddings_np = np.array(embeddings, dtype=np.float32)
    print(f"Embeddings shape: {embeddings_np.shape}")

    # Fit UMAP
    n_neighbors = min(15, len(paths) - 1)
    reducer = umap.UMAP(
        n_components=2, n_neighbors=n_neighbors,
        min_dist=0.15, spread=2.5, metric="cosine", random_state=42,
    )
    coords = reducer.fit_transform(embeddings_np)

    # Normalize to 0-1
    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1

    positions = {}
    for i, path in enumerate(paths):
        x = float((coords[i, 0] - mins[0]) / ranges[0])
        y = float((coords[i, 1] - mins[1]) / ranges[1])
        positions[path] = {"x": x, "y": y}
        print(f"  {path}: ({x:.3f}, {y:.3f})")

    # Push to Firestore
    print(f"\nPushing to Firestore (project={PROJECT_ID}, workspace={WORKSPACE_ID})...")
    store = FirestoreDataStore(project_id=PROJECT_ID, workspace_id=WORKSPACE_ID)

    for path, pos in positions.items():
        store.layout.store_position(path, pos["x"], pos["y"], embeddings_np[paths.index(path)].tobytes())

    # Store UMAP model
    model_data = {"reducer": reducer, "mins": mins, "maxs": maxs, "ranges": ranges}
    store.layout.store_model(pickle.dumps(model_data), len(paths))

    print(f"Done! Pushed {len(positions)} positions + UMAP model to Firestore")
    conn.close()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script**

```bash
cd orchestrator
GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json \
DB_PATH=~/orrery-data/orrery.db \
  .venv/bin/python scripts/fit_umap_google.py
```

Expected output: 30+ domains embedded, UMAP fitted, positions pushed to Firestore.

- [ ] **Step 3: Verify positions in Firestore**

```bash
curl -s https://orrery-orchestrator-469580747258.us-central1.run.app/graph | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d[\"domain_positions\"])} domains with positions')"
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/scripts/fit_umap_google.py
git commit -m "feat: UMAP fitting script with Google Vertex AI embeddings"
```

---

## Task 3: Create Firestore Vector Indexes

**Files:**
- Create: `orchestrator/scripts/create_vector_indexes.sh`

- [ ] **Step 1: Write the index creation script**

```bash
#!/bin/bash
# orchestrator/scripts/create_vector_indexes.sh
# Creates Firestore vector indexes for entity and chunk embedding search.
# Run once per project. Takes 5-30 min to build.

PROJECT_ID="${1:-noospheric-orrery}"

echo "Creating entity embedding vector index..."
gcloud firestore indexes composite create \
  --project=$PROJECT_ID \
  --collection-group=entities \
  --query-scope=COLLECTION \
  --field-config=vector-config='{"dimension":"768","flat":"{}"}',field-path=embedding

echo "Creating chunk embedding vector index..."
gcloud firestore indexes composite create \
  --project=$PROJECT_ID \
  --collection-group=chunks \
  --query-scope=COLLECTION \
  --field-config=vector-config='{"dimension":"768","flat":"{}"}',field-path=embedding

echo "Indexes created. They may take 5-30 minutes to build."
echo "Check status: https://console.firebase.google.com/project/$PROJECT_ID/firestore/indexes"
```

Note: 768 dimensions for text-embedding-004 (not 384 for all-MiniLM-L6-v2).

- [ ] **Step 2: Run the script**

```bash
chmod +x orchestrator/scripts/create_vector_indexes.sh
./orchestrator/scripts/create_vector_indexes.sh noospheric-orrery
```

- [ ] **Step 3: Wait for indexes to build (check Firebase Console)**

- [ ] **Step 4: Commit**

```bash
git add orchestrator/scripts/create_vector_indexes.sh
git commit -m "feat: Firestore vector index creation script (768-dim)"
```

---

## Task 4: Wire Embeddings into Ingest Pipeline

**Files:**
- Modify: `orchestrator/src/routes/ingest.py`
- Modify: `orchestrator/src/repositories/firestore_store.py`

- [ ] **Step 1: Update Firestore entity storage to use Vector type**

In `firestore_store.py`, update `FirestoreEntityRepository.create()` and add a method to store embeddings as Firestore Vector:

```python
# In FirestoreEntityRepository
def store_embedding_vector(self, entity_id: str, embedding: list[float]):
    """Store embedding as a Firestore Vector field for find_nearest() queries."""
    from google.cloud.firestore_v1.vector import Vector
    self._col.document(entity_id).update({"embedding": Vector(embedding)})
```

Add similar method to `FirestoreChunkRepository`.

- [ ] **Step 2: Update ingest to embed entities after extraction**

In `ingest.py`, after entities are stored, call the embedding service and store vectors:

```python
# After entity extraction loop in _ingest_document():
if entity_count > 0:
    try:
        from ..services.embedding import embed_texts
        entity_names = [...]  # collect names from extracted entities
        embeddings = embed_texts(entity_names)
        for name, embedding in zip(entity_names, embeddings):
            # Find entity ID and store vector
            ...
    except Exception as e:
        print(f"Embedding failed (non-fatal): {e}")
```

- [ ] **Step 3: Test by ingesting a document**

```bash
curl -s -X POST https://orrery-orchestrator-469580747258.us-central1.run.app/ingest \
  -F "file=@test.md" | python3 -m json.tool
```

Then verify embedding field exists on entity docs in Firestore Console.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/routes/ingest.py orchestrator/src/repositories/firestore_store.py
git commit -m "feat: embed entities via Vertex AI during ingest"
```

---

## Task 5: Replace FAISS with Firestore Vector Search

**Files:**
- Modify: `orchestrator/src/pipeline/search/retrieval.py`
- Modify: `orchestrator/src/routes/search.py`

- [ ] **Step 1: Add Firestore vector search to retrieval.py**

```python
# New function in retrieval.py
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector

def search_entities_firestore(store, query_embedding: list[float], top_k: int = 20):
    """Vector search on Firestore entities using find_nearest()."""
    collection = store._db.collection(f"workspaces/{store._workspace_id}/entities")
    results = collection.find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_embedding),
        distance_measure=DistanceMeasure.DOT_PRODUCT,
        limit=top_k,
    ).get()
    return [{"id": doc.id, **doc.to_dict()} for doc in results]
```

Add similar function for chunks.

- [ ] **Step 2: Update search route to use vector search**

Replace `_simple_search()` in `search.py` with proper vector search:

```python
# In search route
from ..services.embedding import embed_text

query_embedding = embed_text(query)
entity_results = search_entities_firestore(store, query_embedding, top_k)
chunk_results = search_chunks_firestore(store, query_embedding, top_k)
```

Keep query expansion via Haiku as an enhancement (Stage 1 of the pipeline).
Keep entity boosting + RRF fusion (Stages 3-4).

- [ ] **Step 3: Test search**

```bash
curl -s "https://orrery-orchestrator-469580747258.us-central1.run.app/search?q=harper+reed" | python3 -m json.tool
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/pipeline/search/retrieval.py orchestrator/src/routes/search.py
git commit -m "feat: Firestore vector search replaces FAISS"
```

---

## Task 6: Backfill Existing Entities/Chunks

**Files:**
- Create: `orchestrator/scripts/backfill_embeddings.py`

- [ ] **Step 1: Write backfill script**

```python
# orchestrator/scripts/backfill_embeddings.py
"""Embed all existing entities and chunks via Vertex AI, store as Firestore vectors."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.services.embedding import embed_texts
from src.repositories.firestore_store import FirestoreDataStore
from google.cloud.firestore_v1.vector import Vector

store = FirestoreDataStore(
    project_id=os.environ.get("FIREBASE_PROJECT_ID", "noospheric-orrery"),
    workspace_id=os.environ.get("FIREBASE_WORKSPACE_ID", "default"),
)

# Backfill entities
entities = store.entities.list(limit=5000)
names = [e.canonical_name for e in entities]
if names:
    print(f"Embedding {len(names)} entities...")
    embeddings = embed_texts(names)
    for entity, embedding in zip(entities, embeddings):
        store._entities._col.document(entity.id).update({"embedding": Vector(embedding)})
    print(f"Done: {len(names)} entities embedded")

# Backfill chunks
chunks = store.chunks.get_all_with_embeddings()
texts = [c.text for c in chunks if c.text]
if texts:
    print(f"Embedding {len(texts)} chunks...")
    embeddings = embed_texts(texts)
    for chunk, embedding in zip(chunks, embeddings):
        if chunk.text:
            store._chunks._col.document(chunk.id).update({"embedding": Vector(embedding)})
    print(f"Done: {len(texts)} chunks embedded")
```

- [ ] **Step 2: Run backfill**

```bash
cd orchestrator
GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json \
  .venv/bin/python scripts/backfill_embeddings.py
```

- [ ] **Step 3: Verify vector search works**

Search for an entity and confirm semantic results.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/scripts/backfill_embeddings.py
git commit -m "feat: backfill script for entity/chunk embeddings"
```

---

## Task 7: Update Domain Layout for Google Embeddings

**Files:**
- Modify: `orchestrator/src/pipeline/domain_layout.py`

- [ ] **Step 1: Replace sentence-transformers with Vertex AI in domain_layout.py**

Change `_get_embed_model()` and all `model.encode()` calls to use the embedding service:

```python
# Replace:
# from sentence_transformers import SentenceTransformer
# embeddings = model.encode(texts, normalize_embeddings=True)

# With:
from ..services.embedding import embed_texts
embeddings_list = embed_texts(texts)
embeddings = np.array(embeddings_list, dtype=np.float32)
```

Remove the `_get_embed_model()` function and the global `_model` variable.

- [ ] **Step 2: Update embedding dimension references**

UMAP model saved with text-embedding-004 produces 768-dim vectors.
Verify `transform()` works with the new dimensionality.

- [ ] **Step 3: Test locally**

```bash
cd orchestrator && .venv/bin/pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/pipeline/domain_layout.py
git commit -m "refactor: domain_layout uses Vertex AI embeddings"
```

---

## Task 8: Update Dependencies and Deploy

**Files:**
- Modify: `orchestrator/pyproject.toml`
- Modify: `orchestrator/Dockerfile`

- [ ] **Step 1: Update pyproject.toml**

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "anthropic[bedrock]>=0.40.0",
    "python-multipart>=0.0.9",
    "umap-learn>=0.5.0",
    "numpy>=1.26.0",
    "mcp>=1.0.0",
    "firebase-admin>=6.0.0",
    "google-cloud-firestore>=2.0.0",
    "google-cloud-aiplatform>=1.50.0",  # Vertex AI embeddings
    # REMOVED: sentence-transformers, faiss-cpu
]
```

- [ ] **Step 2: Update Dockerfile**

No changes needed — sentence-transformers was never baked into the image. The Dockerfile is already clean. Vertex AI calls are HTTP-based, no model to load.

- [ ] **Step 3: Run all tests**

```bash
cd orchestrator && .venv/bin/pytest tests/ -v
```

- [ ] **Step 4: Redeploy orchestrator**

```bash
cd orchestrator && gcloud run deploy orrery-orchestrator \
  --source . --region us-central1 --platform managed \
  --allow-unauthenticated \
  --set-env-vars="DB_BACKEND=firestore,FIREBASE_PROJECT_ID=noospheric-orrery,..." \
  --memory=2Gi --cpu=1 --timeout=300
```

- [ ] **Step 5: Redeploy frontend (if any changes)**

```bash
cd frontend && npx vercel --yes --prod
```

- [ ] **Step 6: Commit**

```bash
git add orchestrator/pyproject.toml orchestrator/Dockerfile
git commit -m "chore: switch to Vertex AI embeddings, remove sentence-transformers + FAISS"
```

---

## Verification Checklist

After all tasks:

- [ ] `/graph` returns domain positions from Firestore (no UMAP compute on request)
- [ ] `/search?q=harper` returns semantic results via Firestore vector search
- [ ] `/ingest` embeds new entities/chunks via Vertex AI after extraction
- [ ] New domains get placed via UMAP `transform()` with Google embeddings
- [ ] All 45 existing tests pass
- [ ] No `sentence-transformers` or `faiss-cpu` in dependencies
- [ ] Cloud Run cold start < 5s (no ML model loading)
