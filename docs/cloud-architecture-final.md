# Cloud Architecture — Final Proposal

## Decision: Firebase Functions + Firestore Vector Search + Cloud Run Jobs

All-Firebase stack. No always-on services. Near-zero idle cost.
Cold starts are the only tradeoff — mitigated by proactive warming.

---

## Architecture Overview

```
Frontend (Vercel)
    ↓ HTTP (authenticated via Firebase JWT)
Orchestrator (Cloud Run service)
    ↓ HTTP calls                    ↓ reads/writes
Embedding Function              Firestore
(Firebase Function, Python)     (database + vector search)
    ↓ returns embeddings            ↑ triggers
                                Firebase Functions (event routing)
                                    ↓ HTTP
                                Cloud Run Job (simmer pipeline)
                                    ↓ LLM calls
                                AWS Bedrock (Sonnet, Haiku)
```

---

## Service 1: Orchestrator (Cloud Run Service)

### Role
API gateway. Handles ingest pipeline, graph data, search, CRUD operations.
This already exists and is deployed.

### Current State: DEPLOYED
- URL: `https://orrery-orchestrator-469580747258.us-central1.run.app`
- Python 3.13, FastAPI, 2GB memory
- Reads/writes Firestore directly via repository pattern
- All 14 routes working

### What Changes
- Remove sentence-transformers dependency from this service (move to Function)
- Ingest pipeline calls Embedding Function for entity embeddings
- Search calls Firestore vector search instead of FAISS
- Graph reads stored positions (already working)

### Inputs/Outputs

#### POST /ingest
```
Input: File upload (multipart)
Pipeline:
  1. Store document in Firestore
  2. Chunk document (local, no external call)
  3. Call Bedrock Sonnet for classification (~2s)
  4. Store domain assignments in Firestore
  5. Load spec from Firestore
  6. If spec exists: call Bedrock Haiku for extraction (~2s per chunk)
  7. Normalize entities (string rules — local)
  8. Store entities + sources in Firestore
  9. Call Embedding Function to embed new entities (~1-15s, cold start)
  10. Store co-occurrence edges
  11. Check thresholds → create job docs in Firestore
Output: { document_id, title, domains, entity_count, jobs_queued }
Total time: 5-20s (dominated by LLM calls + potential embedding cold start)
```

#### GET /graph
```
Input: None (workspace scoped via auth)
Pipeline:
  1. Read domain positions from Firestore (instant)
  2. Read all entities + domain weights from Firestore
  3. Read trade routes from Firestore
  4. If new domains without positions: circular fallback placement
Output: { domain_positions, entities, trade_routes, domain_specs, ... }
Total time: 1-3s (Firestore reads only, no computation)
```

#### GET /search
```
Input: query string, top_k
Pipeline:
  1. (Optional) Call Bedrock Haiku for query expansion (~1-2s)
  2. Call Embedding Function to embed query (~1-15s, cold start)
  3. Firestore vector search on entities (~100ms)
  4. Firestore vector search on chunks (~100ms)
  5. Exact match on entity names (Firestore query)
  6. Entity-based chunk boosting (local computation)
  7. RRF fusion (local computation)
Output: { entities, chunks, sub_queries_used, total_entities, total_chunks }
Total time: 2-20s (dominated by Haiku expansion + potential embedding cold start)
```

### Cold Start Mitigation
- Orchestrator itself: ~2s cold start (lightweight Python, no ML models)
- Set min-instances=1 if budget allows (~$30/mo)
- Or accept 2s cold start — acceptable for API gateway

---

## Service 2: Embedding Function (Firebase Function, Python)

### Role
Loads sentence-transformers model. Returns embeddings for text.
Also handles UMAP transform for new domain placement.

### Implementation
Firebase Cloud Functions v2, Python runtime.

```python
# functions/embed/main.py

@functions_framework.http
def embed(request):
    """Embed texts using all-MiniLM-L6-v2."""
    data = request.get_json()
    texts = data["texts"]
    model = _get_model()  # cached across invocations if warm
    embeddings = model.encode(texts, normalize_embeddings=True)
    return {"embeddings": embeddings.tolist()}

@functions_framework.http
def umap_transform(request):
    """Place a new domain using saved UMAP model."""
    data = request.get_json()
    domain_text = data["text"]
    model_blob = data["model_blob"]  # pickled UMAP reducer from Firestore
    # ... transform and return position
    return {"x": float, "y": float}
```

### Inputs/Outputs

#### POST /embed
```
Input:  { "texts": ["harper reed", "AI strategy", ...] }
Output: { "embeddings": [[0.1, 0.2, ...384 floats], ...] }
Model: all-MiniLM-L6-v2 (384 dimensions)
Cold start: 10-15s (model download + load)
Warm: ~50ms for batch of 100
Memory: 512MB
Timeout: 60s (more than enough)
```

#### POST /umap_transform
```
Input:  { "text": "domain path. doc titles. entity names.", "model_blob": bytes }
Output: { "x": 0.45, "y": 0.72 }
Cold start: same as embed (shares model load)
Warm: ~1s
Memory: 512MB
Timeout: 60s
```

### Caveats
- **Cold start is the main issue**: 10-15s to download + load model from HuggingFace
- **Mitigation**: Pre-download model at build time (`pip install sentence-transformers` includes it in some configs, or explicit download in Dockerfile equivalent)
- **Mitigation**: Proactive warming — ping function when user signs in or navigates
- **Mitigation**: Use Google Cloud Storage to cache the model (faster than HuggingFace CDN)
- **Cost**: Near zero. Free tier covers thousands of invocations
- **Alternative**: If cold start is unacceptable, switch to Vertex AI Embeddings (managed, no cold start, but different model/embedding space)

### Proactive Warming Strategy
```
User signs in          → frontend pings /embed with dummy text
User opens upload page → frontend pings /embed
User opens galaxy      → no embedding needed (positions from Firestore)
User searches          → cold start blends with Haiku expansion time
```

---

## Service 3: Firestore Vector Search (No separate service)

### Role
Replaces FAISS for semantic entity/chunk search. Uses Firestore's built-in
vector similarity queries.

### Implementation
No separate service — vector search is a Firestore feature. Embeddings stored
as vector fields on entity and chunk documents.

### Firestore Schema Changes
```
workspaces/{id}/entities/{entityId}:
  canonicalName: string
  type: string
  embedding: vector(384)     ← NEW: vector field for similarity search
  sourceCount: number

workspaces/{id}/chunks/{chunkId}:
  documentId: string
  text: string
  embedding: vector(384)     ← NEW: vector field for similarity search
```

### Vector Index Creation
```
// firestore.indexes.json
{
  "indexes": [
    {
      "collectionGroup": "entities",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "embedding", "vectorConfig": { "dimension": 384, "flat": {} } }
      ]
    },
    {
      "collectionGroup": "chunks",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "embedding", "vectorConfig": { "dimension": 384, "flat": {} } }
      ]
    }
  ]
}
```

### Query Pattern
```python
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

# Embed query
query_embedding = call_embedding_function(query_text)

# Search entities
results = (
    db.collection("workspaces/{id}/entities")
    .find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_embedding),
        distance_measure=DistanceMeasure.COSINE,
        limit=20,
    )
    .get()
)
```

### Inputs/Outputs

#### Entity Search
```
Input:  384-dim query embedding
Output: Top-K entities sorted by cosine similarity
  [{ id, canonicalName, type, sourceCount, distance }]
Latency: ~100ms
```

#### Chunk Search
```
Input:  384-dim query embedding
Output: Top-K chunks sorted by cosine similarity
  [{ id, text, documentId, distance }]
Latency: ~100ms
```

### Caveats
- **Embedding model matters**: Firestore doesn't care what model produced the vectors, but all vectors must be from the same model. If we switch models later, ALL embeddings need re-computation.
- **384 dimensions**: all-MiniLM-L6-v2 produces 384-dim vectors. Firestore supports up to 2048 dimensions.
- **Flat index**: For <10K vectors, flat (brute-force) is fine. For larger corpora, Firestore may offer ANN indexes.
- **Cost**: Normal Firestore read pricing. Vector search adds no extra cost beyond the reads.
- **Current shortcut**: We're using simple keyword matching. Migration requires: (1) storing embeddings on entity/chunk docs, (2) calling Embedding Function during ingest, (3) changing search route to use find_nearest.

### Migration Steps
1. Add `embedding` vector field to entity/chunk Firestore schema
2. During ingest: after entity creation, call Embedding Function → store embedding on entity doc
3. Rebuild search route to use `find_nearest()` instead of FAISS
4. Backfill: run Embedding Function on all existing entities/chunks
5. Keep query expansion via Haiku (unchanged)
6. Keep entity-based boosting + RRF fusion (unchanged, just different retrieval source)

---

## Service 4: Simmer Worker (Cloud Run Job)

### Role
Runs long-running simmer-sdk refinement loops. Produces extraction specs.
Only service that exceeds Firebase Function limits.

### Why Cloud Run Job (not Function)
- Simmer runs take 30-50 minutes
- Firebase Functions max: 9 minutes (540s)
- Cloud Run Jobs max: 24 hours
- Cloud Run Jobs: triggered on demand, pay only for runtime, scale to zero

### Implementation

#### Docker Image
```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY simmer-sdk/ /tmp/simmer-sdk/
RUN pip install /tmp/simmer-sdk/ && rm -rf /tmp/simmer-sdk/
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY worker/ worker/
CMD ["python", "-m", "worker.main"]
```

#### Dependencies
- simmer-sdk (iterative refinement)
- anthropic[bedrock] (Bedrock API calls)
- google-cloud-firestore (read/write results)
- firebase-admin (auth)

#### Job Types

##### simmer_general
```
Trigger: Firebase Function detects job doc with type="simmer_general", status="queued"
Input:
  - 10 sample documents from Firestore
  - Judge criteria: "Coverage & Depth", "Precision & Quality"
  - 5 iterations
Process:
  Phase 1 — Golden Set:
    - simmer-sdk iterates on a golden entity set
    - Each iteration: generate candidate → judge with 2 Sonnet calls → score → synthesize
    - 5 iterations × 2 judges × ~3 min each = ~30 min
  Phase 2 — Extraction Spec:
    - simmer-sdk iterates on a Haiku prompt
    - Tests prompt against golden set for recall/precision
    - 5 iterations × ~2 min each = ~10 min
Output:
  - General extraction spec (text, stored in Firestore specs collection)
  - Golden entity set (JSON, stored in Firestore)
  - Per-iteration scores (stored in Firestore simmerIterations)
  - Creates extract_batch job doc in Firestore
Duration: 30-50 minutes
Cost: ~$0.50-2.00 in Bedrock (Sonnet judging) + ~$0.05 Cloud Run compute
```

##### simmer_domain
```
Trigger: Firebase Function detects job doc with type="simmer_domain"
Input:
  - Documents from specific domain
  - General spec as base
  - Same judge criteria, 5 iterations
Output:
  - Domain-specific extraction spec
  - Domain-specific golden set
Duration: 30-50 minutes
```

##### extract_batch
```
Trigger: Firebase Function detects job doc with type="extract_batch"
Input:
  - Spec (general or domain)
  - All documents in scope
Process:
  - For each document: call Haiku with spec on each chunk
  - Normalize extracted entities
  - Compute co-occurrence edges
  - Call Embedding Function to embed new entities
Output:
  - Entities stored in Firestore
  - Entity sources stored
  - Co-occurrence relationships stored
Duration: 2-10 minutes
```

### Trigger Chain
```
1. User uploads docs → ingest creates job doc in Firestore
   (simmer_general if no spec, simmer_domain if threshold reached)

2. Firebase Function (Node.js, lightweight):
   - Watches: workspaces/{id}/jobs/{jobId}
   - Filters: status == "queued"
   - Action: Calls Cloud Run Job execution API
   - Timeout: 30s (just triggers, doesn't wait)

3. Cloud Run Job starts:
   - Reads job doc from Firestore
   - Marks job as "running"
   - Runs simmer-sdk pipeline (30-50 min)
   - Writes spec + iterations to Firestore
   - Marks job as "completed"
   - Creates follow-up jobs if needed

4. Firebase Function detects extract_batch job → triggers another Cloud Run Job
```

### Caveats
- **simmer-sdk file I/O**: Currently reads/writes judgment files to disk. Cloud Run Jobs have a writable filesystem (ephemeral), so this works as-is. Judgment files are lost after job completes — if we want to keep them, write to Firestore or Cloud Storage.
- **Worker code migration**: The worker currently uses raw SQLite. Needs migration to repository pattern (like orchestrator) or use orchestrator API endpoints for Firestore access.
- **Cold start**: ~15-20s for Cloud Run Job to start. Negligible for a 30-50 min job.
- **Cost**: ~$0.05 per job in Cloud Run compute. Bedrock LLM calls dominate cost.
- **Concurrency**: Cloud Run Jobs can run multiple instances. Set max-instances=1 initially to avoid race conditions on Firestore writes.

---

## Cost Summary

| Service | Monthly Cost (small team, ~100 docs) |
|---------|--------------------------------------|
| Orchestrator (Cloud Run) | $0-5 (min-instances=0, pay per request) |
| Embedding Function | $0 (free tier) |
| Firestore | $0-5 (reads/writes + storage) |
| Cloud Run Jobs (simmer) | $1-5 (few jobs per month) |
| Vercel (frontend) | $0 (free tier) |
| AWS Bedrock | $10-50 (LLM calls — the real cost) |
| **Total** | **$11-65/month** |

With 100K Bedrock credits, the infrastructure cost is effectively $0-10/month.

---

## Cold Start Warming Strategy

| User Action | What to Warm |
|-------------|-------------|
| Sign in | Ping Embedding Function with dummy text |
| Open upload page | Ping Embedding Function |
| Upload doc | Embedding called as part of pipeline (may cold start) |
| Open galaxy | No warming needed (Firestore reads only) |
| Search | Embedding called for query (may cold start, blends with Haiku latency) |
| Simmer triggered | Cloud Run Job starts (15-20s, negligible for 30-50 min job) |

### Implementation
```javascript
// Frontend: warm embedding function proactively
async function warmEmbeddingService() {
  try {
    await fetch(`${API_URL}/internal/warm-embedding`, { method: "POST" });
  } catch {} // fire-and-forget
}

// Call on sign-in and page navigation
onAuthChange((user) => { if (user) warmEmbeddingService(); });
```

---

## Migration Order

1. **Embedding Function** (1 day) — Deploy Python Firebase Function with sentence-transformers
2. **Firestore Vector Search** (1 day) — Add vector fields, create indexes, update search route
3. **Wire Orchestrator** (0.5 day) — Ingest calls Embedding Function, search uses Firestore vectors
4. **Cloud Run Job** (1-2 days) — Docker image with simmer-sdk, Firebase Function trigger
5. **Warming strategy** (0.5 day) — Frontend pings on sign-in/navigation
6. **Backfill** (0.5 day) — Embed all existing entities/chunks via Embedding Function

**Total: ~5 days**

---

## Files Reference

| Component | Current Files | What Changes |
|-----------|--------------|--------------|
| Orchestrator routes | `orchestrator/src/routes/*.py` | Remove FAISS/embedding imports, call Embedding Function HTTP |
| Embedding Function | NEW: `functions/embed/main.py` | New Python function |
| Search pipeline | `orchestrator/src/pipeline/search/` | Replace FAISS retrieval with Firestore find_nearest |
| UMAP layout | `orchestrator/src/pipeline/domain_layout.py` | Call Embedding Function instead of local model |
| Entity normalization | `orchestrator/src/pipeline/embedding_normalizer.py` | Call Embedding Function for similarity computation |
| Worker | `worker/src/` | Migrate to Firestore, add to Cloud Run Job Docker image |
| Firebase triggers | `functions/index.js` | Add job → Cloud Run Job trigger |
| Firestore indexes | `firestore.indexes.json` | Add vector indexes for entities + chunks |
