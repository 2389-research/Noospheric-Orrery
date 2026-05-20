# Cloud Compute Services — Architecture for Firebase Redesign

These are the compute-heavy services that need proper cloud architecture.
Each section documents what the service does, its inputs/outputs, resource
requirements, and recommended cloud implementation.

---

## 1. Embedding Service (sentence-transformers)

### What it does
Converts text into 384-dimensional vectors using `all-MiniLM-L6-v2`.
Used by three subsystems: UMAP layout, FAISS search, entity normalization.

### Model
- `sentence-transformers/all-MiniLM-L6-v2`
- ~90MB download from HuggingFace
- ~300MB in memory once loaded
- Inference: ~5ms per text, ~50ms for batch of 100

### API Surface
```
POST /embed
Input:  { "texts": ["text1", "text2", ...] }
Output: { "embeddings": [[0.1, 0.2, ...], ...] }  // array of 384-dim float arrays
```

### Callers
| Caller | When | Batch Size |
|--------|------|-----------|
| UMAP layout (full_fit) | Domain count doubles | 10-100 domains |
| UMAP layout (transform) | New domain added | 1 domain |
| Search (embed query) | Every search request | 1-5 sub-queries |
| Search (embed entities) | After ingest/rebuild | 1-1000 entities |
| Search (embed chunks) | After ingest/rebuild | 1-500 chunks |
| Normalization (batch) | Manual trigger | All entities (~1000+) |

### Resource Profile
- Memory: 512MB minimum (model + inference)
- CPU: 0.5 cores sufficient
- Latency requirement: <100ms for single text, <1s for batch of 100
- Stateless (no persistent data, just the model)

### Recommended Implementation
Dedicated Cloud Run service, min-instances=1 (always warm).
- Image: Python 3.13 + sentence-transformers
- Model baked into Docker image at build time
- Simple FastAPI with single `/embed` endpoint
- All other services call this via HTTP
- Cost: ~$15-30/mo for always-warm micro instance

---

## 2. UMAP Layout Service

### What it does
Computes 2D positions for domains on the galaxy map using UMAP
dimensionality reduction on domain embeddings.

### Dependencies
- Embedding service (to embed domain texts)
- `umap-learn` library (requires `numba` JIT compiler)

### Operations

#### full_fit — Recompute all positions
```
Input:
  - List of domain paths with doc_count > 0
  - For each domain: path string, top 6 doc titles, top 12 entity names
Output:
  - { domain_path: { x: float, y: float } } for all domains (0-1 normalized)
  - Fitted UMAP model (pickled, ~50KB) for future transform() calls
Side effects:
  - Stores positions in Firestore (domainLayout collection)
  - Stores model in Firestore (layoutModel collection)
Triggers:
  - First time (no positions exist)
  - Domain count doubles since last fit
Duration: 5-15 seconds
```

#### transform — Place a single new domain
```
Input:
  - New domain path + text (path, doc titles, entity names)
  - Saved UMAP model from previous full_fit
Output:
  - { x: float, y: float } (0-1 normalized)
Side effects:
  - Stores position in Firestore
Triggers:
  - New domain created during ingest
Duration: 1-2 seconds
```

### Resource Profile
- Memory: 1GB (UMAP + numba JIT compilation)
- CPU: 1 core (UMAP is CPU-bound)
- Duration: 5-15s for full_fit, 1-2s for transform
- Infrequent (only on domain changes)

### Current Implementation
- `orchestrator/src/pipeline/domain_layout.py`
- Calls `_build_domain_text()` → embeds with sentence-transformers → UMAP fit/transform
- Stores positions in DB (SQLite domain_layout table / Firestore domainLayout collection)

### Recommended Implementation
- Run as part of the embedding service (same container, since it needs embeddings)
- Or: Firebase Function triggered by domain creation → calls embedding service → UMAP → store
- Or: Background Cloud Run job triggered by Firestore write to domains collection

---

## 3. Search Pipeline (FAISS)

### What it does
5-stage hybrid search combining semantic (vector) and keyword matching.

### Stages

#### Stage 1: Query Expansion
```
Input:  User query string
Output: 3-5 sub-queries
Method: Haiku LLM call via Bedrock
Duration: 1-2 seconds
Dependencies: AWS Bedrock (Haiku model)
```

#### Stage 2: Retrieval (3 channels per sub-query)
```
Channel A — FAISS Entity Search:
  Input:  Query embedding (384-dim)
  Output: Top-K entities with cosine similarity scores
  Dependencies: FAISS index built from entity embeddings

Channel B — FAISS Chunk Search:
  Input:  Query embedding (384-dim)
  Output: Top-K document chunks with similarity scores
  Dependencies: FAISS index built from chunk embeddings

Channel C — Exact Match:
  Input:  Query string
  Output: Entities whose names contain query terms
  Dependencies: Entity list (simple string matching)
```

#### Stage 3: Entity-Based Chunk Boosting
```
Input:  Entity results + chunk results
Output: Chunks re-scored based on entity overlap
Method: Hub dampening (frequent entities get less boost)
```

#### Stage 4: RRF Fusion
```
Input:  Results from all sub-queries
Output: Single ranked list of entities + chunks
Method: Reciprocal Rank Fusion across sub-queries
```

#### Stage 5: Return
```
Output: {
  query: string,
  entities: [{ id, name, type, score, source_count, paths }],
  chunks: [{ chunk_id, text, document_id, document_title, score }],
  sub_queries_used: string[],
  total_entities: int,
  total_chunks: int
}
```

### FAISS Index Management
```
Build indexes:
  Input: All entities with embeddings, all chunks with embeddings
  Output: Two FAISS IndexFlatIP indexes (in-memory)
  Storage: Indexes live in memory only, rebuilt from DB embeddings
  Duration: 2-5 seconds for ~1000 entities

Embed new entities/chunks:
  Input: Entities/chunks without embeddings
  Output: Embeddings stored in DB
  Method: Calls sentence-transformers on the name/text
```

### Resource Profile
- Memory: 512MB (FAISS indexes + model)
- CPU: 0.5 cores
- Latency: 2-4s per search (dominated by Haiku query expansion)
- FAISS indexes need to be in memory (not on disk for serverless)

### Current Implementation
- `orchestrator/src/pipeline/search/` (6 modules)
  - `config.py` — SearchConfig
  - `models.py` — ScoredEntity, ScoredChunk, SearchResponse
  - `expansion.py` — Haiku query expansion
  - `retrieval.py` — FAISS index building, entity/chunk search, embeddings
  - `entity_boost.py` — Hub dampening boost
  - `fusion.py` — RRF fusion
  - `pipeline.py` — Main entry point

### Recommended Implementation
- **Option A**: FAISS in embedding service (same container that loads the model)
  - Indexes rebuilt on startup from Firestore embeddings
  - Search requests routed to this service
  - Pros: one service for all embedding + search ops
  - Cons: index rebuild on cold start

- **Option B**: Firestore native vector search
  - Store embeddings as vector fields on entity/chunk documents
  - Use Firestore's built-in vector similarity queries
  - Pros: no FAISS, no separate service, scales automatically
  - Cons: Google's vector search may not match FAISS quality, tied to Firestore

- **Option C**: Vertex AI Vector Search
  - Managed vector database service
  - Upload embeddings, query via API
  - Pros: scales, managed, production-grade
  - Cons: additional cost, more setup

### Current Cloud Shortcut
Simple keyword matching on entity names + document titles.
No embeddings, no FAISS, no query expansion. Works but much lower quality.

---

## 4. Simmer Pipeline (simmer-sdk)

### What it does
Iteratively refines extraction specs through LLM judge evaluation.
Produces a "golden set" of reference entities and an optimized Haiku prompt
for entity extraction.

### Operations

#### simmer_general — General extraction spec
```
Input:
  - 10 sample documents from the corpus
  - 2 judge criteria: "Coverage & Depth", "Precision & Quality"
  - 5 iterations
Output:
  - Phase 1: Golden entity set (JSON, representative entities)
  - Phase 2: Extraction spec (text prompt for Haiku)
  - Per-iteration scores + key changes + ASI
Side effects:
  - Spec stored in specs collection
  - Iteration history in simmerIterations collection
  - Triggers extract_batch job for all classified documents
Duration: 30-50 minutes
Dependencies: AWS Bedrock (Sonnet for judging, Haiku for extraction), simmer-sdk
```

#### simmer_domain — Domain-specific spec
```
Input:
  - Documents from a specific domain
  - General spec as base
  - 2 judge criteria
  - 5 iterations
Output:
  - Domain-specific extraction spec
  - Domain-specific golden set
Duration: 30-50 minutes
Trigger: Domain reaches threshold doc count (default 20)
```

#### extract_batch — Run spec against documents
```
Input:
  - Spec (general or domain)
  - All documents in scope
Output:
  - Extracted entities per document
  - Co-occurrence relationships
  - Updated entity_sources records
Duration: 2-10 minutes depending on doc count
Dependencies: AWS Bedrock (Haiku)
```

### Resource Profile
- Memory: 512MB
- CPU: 0.5 cores (mostly waiting on LLM calls)
- Duration: 30-50 minutes (too long for Firebase Functions 9-min limit)
- Infrequent (triggered by threshold crossing)

### Current Implementation
- `worker/src/jobs/simmer_general.py` — General spec simmering
- `worker/src/jobs/simmer_domain.py` — Domain-specific simmering
- `worker/src/jobs/extract_batch.py` — Batch extraction
- `worker/src/jobs/runner.py` — Job picking + status management
- Dependencies: simmer-sdk (installed from local path)

### Recommended Implementation
- **Cloud Run job** (not service) — runs on demand, can take up to 60 minutes
- Triggered by Firebase Function watching Firestore jobs collection
- Firebase Function fires HTTP request to Cloud Run job endpoint
- Cloud Run job runs simmer pipeline, writes results to Firestore
- Needs: simmer-sdk in Docker image, Firestore-aware job runner

### Data Flow
```
User uploads docs
  → Ingest pipeline classifies + extracts with existing spec
  → If no general spec exists → creates simmer_general job
  → If domain threshold reached → creates simmer_domain job
  → Firebase Function detects job → triggers Cloud Run worker
  → Worker runs simmer-sdk loop (30-50 min)
  → Worker stores spec in Firestore
  → Worker creates extract_batch job
  → Firebase Function triggers batch extraction
  → Batch extraction runs spec against docs
  → Entities stored in Firestore
  → Done
```

---

## Service Dependency Map

```
Frontend (Vercel)
    ↓ HTTP
Orchestrator (Cloud Run) — API gateway, ingest pipeline, graph data
    ↓ HTTP                   ↓ Firestore
Embedding Service        Firestore (database)
(Cloud Run, warm)          ↑ triggers
    |                    Firebase Functions (event routing)
    |                        ↓ HTTP
    +-- UMAP compute     Worker (Cloud Run job)
    +-- Search/FAISS         |
    +-- Normalization        +-- simmer-sdk
                             +-- Bedrock LLM calls
                             +-- Firestore writes

External:
  AWS Bedrock (Sonnet, Haiku) — all LLM calls from orchestrator + worker
```
