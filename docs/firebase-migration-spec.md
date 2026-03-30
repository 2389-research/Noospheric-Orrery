# Firebase Migration Spec — Noospheric Orrery

## Current Architecture (What Exists)

### Services
- **Orchestrator** (FastAPI, Python): REST API + WebSocket. Handles ingest, classification, extraction, normalization, search, graph data. Runs on port 8100.
- **Worker** (Python): Polls SQLite every 5s for queued jobs. Runs simmer_general, simmer_domain, extract_batch. Jobs take 30-50 min for simmering.
- **Frontend** (Next.js 16): Upload, pipeline dashboard, entity explorer, galaxy viz. Communicates with orchestrator via fetch + WebSocket.

### Storage
- **SQLite** (WAL mode): Single file at `~/orrery-data/orrery.db`. Both orchestrator and worker read/write. 14+ tables.
- **Filesystem**: Uploaded docs at `~/orrery-data/documents/`, simmered specs at `~/orrery-data/specs/`.
- **In-memory**: FAISS indexes rebuilt from SQLite BLOBs on startup. UMAP model pickled in SQLite.

### External Dependencies
- **AWS Bedrock**: All LLM calls (Sonnet for classification, Haiku for extraction/query expansion). Uses `AsyncAnthropicBedrock` with IAM credentials.
- **simmer-sdk**: Iterative refinement for specs. Calls Bedrock internally. Writes judgment files to disk.
- **sentence-transformers**: all-MiniLM-L6-v2 for entity/chunk/domain embeddings. Runs locally.
- **UMAP**: Domain layout computation. Fitted model stored in SQLite.

### Auth
- None. Single-user, local deployment.

### Key Data Flows

#### Ingest (synchronous, ~5-15s per doc)
```
Input: file upload or directory path
Steps:
  1. Hash content → dedup check
  2. Store document + chunk into SQLite
  3. Build excerpt → classify via Sonnet (~2s)
  4. Normalize domain labels → create/assign domains
  5. Load specs (general + domain cascade)
  6. Extract entities via Haiku per chunk (~1-3s per spec)
  7. Normalize entities (merge_map check)
  8. Compute co-occurrence edges
  9. Embed new entities/chunks for search
  10. Check thresholds → queue simmer/extract jobs
Output: { document_id, title, domains, entity_count, jobs_queued }
```

#### Simmer (async worker, 30-50 min)
```
Input: job { type: simmer_general|simmer_domain, target: domain_path }
Steps:
  1. Pick job from SQLite, mark running
  2. Gather corpus documents for this domain
  3. Phase 1: Simmer golden set (5 iterations, 2 judges)
  4. Phase 2: Simmer extraction spec (5 iterations, 2 judges)
  5. Store spec + golden set in SQLite + filesystem
  6. Record per-iteration scores in simmer_iterations table
  7. Queue extract_batch job for all docs in scope
Output: spec file on disk, iteration history in DB, follow-up extract job queued
```

#### Batch Extraction (async worker, 2-10 min)
```
Input: job { type: extract_batch, target: domain_path }
Steps:
  1. Load spec for domain
  2. Extract entities from all docs in domain using spec
  3. Normalize new entities
  4. Compute co-occurrence edges
  5. Store results, mark job complete
Output: new entities + relationships in DB
```

#### Search (synchronous, ~1-3s)
```
Input: query string, top_k
Steps:
  1. Expand query → 3-5 sub-queries via Haiku
  2. For each sub-query: FAISS entity search + FAISS chunk search + exact match
  3. Entity-based chunk boosting (hub dampening)
  4. RRF fusion across sub-queries
  5. Broadcast results via WebSocket (triggers viz glow)
Output: { entities: [...], chunks: [...], total_entities, total_chunks }
```

#### Graph Data (synchronous, ~0.5s)
```
Input: GET /graph
Steps:
  1. Load domain positions from domain_layout table (UMAP-based, cached)
  2. If new domains exist: run umap.transform() to place them
  3. Load all entities with domain weights
  4. Load trade routes (domain-domain co-occurrence counts)
  5. Compute colors, specs, active simmers
Output: { domain_positions, entities, trade_routes, domain_specs, ... }
```

#### Star Graph (synchronous, ~0.2s)
```
Input: GET /entities/{id}/star-graph
Steps:
  1. Get entity's source documents
  2. Get co-occurring entities via relationships table
  3. For each co-entity, find shared documents
Output: { entity, documents, co_entities: [{...shared_doc_ids}] }
```

---

## Target Architecture (Firebase)

### Multi-Tenancy Model

**Hierarchy**: Organization → Workspace (segment) → Data

- **Organization**: A team/company. Has members with roles (admin, editor, viewer).
- **Workspace**: A named knowledge graph segment. "2389 Meeting Notes", "Warhammer Research", "Legal Docs". Each has its own domain taxonomy, extraction specs, entities. A user can have multiple workspaces.
- **Shared data**: Some entities/domains may span workspaces (future — start isolated).

### Firestore Schema

```
organizations/
  {orgId}/
    name: string
    createdAt: timestamp

    members/
      {userId}/
        role: "admin" | "editor" | "viewer"
        joinedAt: timestamp

    workspaces/
      {workspaceId}/
        name: string
        description: string
        createdBy: userId
        createdAt: timestamp
        stats: { documentCount, entityCount, domainCount }

        documents/
          {docId}/
            title: string
            contentHash: string
            status: "pending" | "classified" | "extracted" | "enriched"
            createdAt: timestamp
            createdBy: userId
            storagePath: string  # Firebase Storage reference

            domains/  # subcollection
              {domainPath}/
                isPrimary: boolean
                confidence: number

            chunks/  # subcollection
              {chunkId}/
                chunkIndex: number
                text: string
                offset: number
                length: number
                embedding: bytes  # or store in a vector index

        domains/
          {domainPath}/  # use path as doc ID, encode slashes
            path: string
            parentPath: string
            documentCount: number
            specVersion: number | null
            layoutX: number  # UMAP position
            layoutY: number
            createdAt: timestamp

        entities/
          {entityId}/
            canonicalName: string
            type: string
            embedding: bytes
            createdAt: timestamp
            sourceCount: number  # denormalized for fast reads

            sources/  # subcollection
              {sourceId}/
                documentId: string
                chunkId: string
                extractionPass: string
                specVersion: number
                jobId: string

        relationships/
          {relId}/
            fromEntity: string
            toEntity: string
            type: "co_occurs"
            weight: number
            sourceChunk: string

        mergeMap/
          {fromName}/
            toEntityId: string

        domainMergeMap/
          {fromLabel}/
            toPath: string

        specs/
          {specId}/
            domainPath: string
            version: number
            specContent: string  # or Storage reference for large specs
            goldenSet: string
            score: number
            createdAt: timestamp

        jobs/
          {jobId}/
            type: "simmer_general" | "simmer_domain" | "extract_batch"
            target: string
            status: "queued" | "running" | "completed" | "failed"
            config: map
            result: map
            createdAt: timestamp
            startedAt: timestamp
            completedAt: timestamp

            iterations/  # subcollection for simmer history
              {iterationId}/
                phase: string
                iteration: number
                scores: map
                composite: number
                keyChange: string
                asi: string
                regressed: boolean

        normalizationQueue/
          {reviewId}/
            entityAId: string
            entityAName: string
            entityBId: string
            entityBName: string
            similarity: number
            status: "pending" | "resolved"
            resolution: "merge" | "keep_separate" | null

        layout/
          model/
            modelBlob: bytes  # pickled UMAP model
            domainCount: number
            createdAt: timestamp
```

### Firebase Storage Structure

```
organizations/{orgId}/workspaces/{workspaceId}/
  documents/{docId}/original.md       # uploaded file
  specs/{domainPath}/v{version}.json  # simmered specs
  specs/{domainPath}/golden_set.json  # golden entity sets
```

### Authentication & Authorization

- **Firebase Auth**: Google sign-in, email/password, SSO
- **Firestore Security Rules**:
  - Read/write gated by org membership
  - Editors can ingest, trigger simmers, resolve normalizations
  - Viewers can search, browse, use viz
  - Admins can manage members, delete workspaces
- **Frontend**: Auth state via `onAuthStateChanged`, token passed to API calls

### Compute Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Frontend (Next.js on Vercel or Firebase Hosting)        │
│  - Auth via Firebase Auth                                │
│  - Firestore listeners for real-time updates             │
│  - Galaxy viz (same Canvas2D, reads from Firestore)      │
└───────────────────────┬──────────────────────────────────┘
                        │
┌───────────────────────┴──────────────────────────────────┐
│  Firebase Functions (2nd gen / Cloud Functions v2)        │
│  - POST /ingest → classify + extract (< 60s timeout ok)  │
│  - GET /search → query expansion + vector search          │
│  - GET /graph → read Firestore + compute if needed        │
│  - POST /normalize → embedding comparison                 │
│  - Firestore triggers: onDocumentCreated → auto-index     │
└───────────────────────┬──────────────────────────────────┘
                        │
┌───────────────────────┴──────────────────────────────────┐
│  Cloud Run (long-running jobs)                           │
│  - Simmer jobs (30-50 min — too long for Functions)      │
│  - Batch extraction jobs                                 │
│  - Triggered by Firestore writes to jobs/ collection     │
│  - Or via Cloud Tasks / Pub/Sub                          │
└───────────────────────┬──────────────────────────────────┘
                        │
┌───────────────────────┴──────────────────────────────────┐
│  External Services                                       │
│  - AWS Bedrock (Sonnet, Haiku) — all LLM calls           │
│  - sentence-transformers (run in Functions/Cloud Run)     │
│  - UMAP (run in Cloud Run for layout computation)        │
└──────────────────────────────────────────────────────────┘
```

### Search Strategy

Options (pick one):
1. **Firestore + Cloud Function**: Store embeddings in Firestore, compute cosine similarity in a Function. Simple but slow for large corpora.
2. **Vertex AI Vector Search**: Google's managed vector DB. Scales well, but adds cost/complexity.
3. **FAISS in Cloud Run**: Keep current FAISS approach, run as a persistent Cloud Run service. Rebuild index periodically from Firestore embeddings.
4. **Firestore Vector Search** (if available in your region): Native vector similarity on Firestore documents.

Recommendation: Start with option 3 (FAISS in Cloud Run) for familiarity, migrate to Vertex AI when scale demands it.

### Real-Time Updates

Replace WebSocket with Firestore listeners:
- Frontend subscribes to `workspaces/{id}/jobs` for pipeline status
- Subscribe to `workspaces/{id}/entities` for new entity arrivals
- Galaxy viz listens for search broadcasts via a `searchEvents` subcollection (TTL'd docs)
- Simmer progress: frontend listens to `jobs/{id}/iterations` subcollection

### UMAP Layout in Firebase

- Fitted UMAP model stored as blob in `layout/model` doc
- Domain positions stored on each domain doc (`layoutX`, `layoutY`)
- On new domain: Cloud Function loads model blob, runs `transform()`, writes position
- On domain count doubling: Cloud Run job re-fits UMAP, updates all positions

---

## Migration Path

### Phase 1: Auth + Hosting (1-2 days)
- Add Firebase Auth to frontend
- Deploy frontend to Vercel or Firebase Hosting
- Orchestrator stays as-is, add auth token validation middleware
- Single workspace per user (no orgs yet)

### Phase 2: Database Migration (3-5 days)
- Abstract DB layer: create interface that both SQLite and Firestore implement
- Migrate tables → Firestore collections
- Denormalize where needed (Firestore != relational)
- Update all queries (SQL → Firestore SDK)
- Keep SQLite as fallback/dev mode

### Phase 3: Compute Migration (2-3 days)
- Move ingest pipeline to Firebase Functions
- Move worker to Cloud Run
- Set up Pub/Sub or Firestore triggers for job dispatch
- Move file storage to Firebase Storage

### Phase 4: Search Migration (1-2 days)
- FAISS service on Cloud Run (persistent, receives embed requests)
- Or Firestore vector search if available
- Query expansion stays in Functions (Haiku call)

### Phase 5: Multi-Tenancy (2-3 days)
- Org + workspace model
- Security rules per org/workspace
- Workspace selector in UI
- Per-workspace UMAP layouts

### Phase 6: Real-Time (1-2 days)
- Replace polling/WebSocket with Firestore listeners
- Search broadcast via Firestore TTL docs
- Live pipeline status updates

---

## Key Decisions Needed

1. **Firestore vs Cloud SQL**: Firestore is simpler for multi-tenant, real-time. Cloud SQL (Postgres) is better for complex queries (joins, aggregations). The current codebase uses many JOINs. Tradeoff: rewrite queries vs managed real-time.

2. **Embedding storage**: Firestore has a 1MB doc limit. Entity embeddings (384-dim float32 = 1.5KB each) fit fine. UMAP model blob (~50KB) fits. FAISS index doesn't — keep in Cloud Run memory or Cloud Storage.

3. **Cost model**: Firestore charges per read/write. The viz page reads all domains + entities on load (~1000 reads). Need to cache aggressively or use a CDN/snapshot endpoint.

4. **simmer-sdk in cloud**: Currently reads/writes files on disk. Needs adaptation for Cloud Storage or Firestore for judgment files and spec artifacts.

5. **Cold start**: Cloud Functions cold start + loading sentence-transformers model = ~10-20s. Options: keep warm, use Cloud Run min instances, or lazy-load embeddings.

6. **Cross-cloud**: Bedrock (AWS) + Firebase (GCP). Latency for LLM calls crosses cloud boundaries. Not a problem for classification/extraction (already 2-3s) but worth noting.

---

## Inputs/Outputs Summary for Planning Agent

### What the planning agent needs to know:

**Current codebase**:
- `orchestrator/src/` — FastAPI app, all pipeline logic, routes, search
- `worker/src/` — Job polling, simmer execution, batch extraction
- `frontend/src/` — Next.js 16 app with Canvas2D viz
- `orchestrator/src/db.py` — Full SQLite schema (source of truth for data model)
- `orchestrator/src/pipeline/` — Pure functions: classifier, extractor, normalizer, search, domain_layout
- `docs/IMPLEMENTATION-NOTES.md` — Gotchas and decisions

**What's pure logic (portable)**:
- `pipeline/classifier.py` — takes text, returns domain classification
- `pipeline/extractor.py` — takes chunks + spec, returns entities
- `pipeline/normalizer.py` — takes entity name, returns canonical ID
- `pipeline/embedding_normalizer.py` — batch entity normalization
- `pipeline/cooccurrence.py` — takes chunk-entity map, returns edges
- `pipeline/search/` — 6-module search pipeline
- `pipeline/domain_layout.py` — UMAP fitting and transform
- `frontend/public/viz/` — entire visualization (HTML + JS modules)

**What's DB-coupled (needs rewrite)**:
- `routes/ingest.py` — heavy SQL throughout
- `routes/graph.py` — complex queries with JOINs
- `routes/entities.py` — filtered queries, star-graph endpoint
- `routes/search.py` — FAISS index management
- `db.py` — schema definition
- `worker/src/jobs/` — all job runners read/write SQLite directly

**What's infra-coupled**:
- WebSocket broadcaster — replace with Firestore listeners
- File storage (docs, specs) — replace with Firebase Storage
- simmer-sdk file I/O — needs Cloud Storage adapter
- FAISS in-memory indexes — needs persistent service
