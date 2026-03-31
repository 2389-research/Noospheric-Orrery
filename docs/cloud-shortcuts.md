# Cloud Deployment Shortcuts — What Needs Proper Implementation

These are temporary compromises made to get the cloud deployment working.
Each needs to be replaced with the proper implementation.

## 1. Search (Simple → FAISS)

**Current shortcut**: Firestore backend uses simple name-matching search
(exact match > contains all terms > any term). No embeddings, no FAISS,
no query expansion, no semantic search.

**Proper implementation**: Migrate the 5-stage search pipeline to work on Firestore:
- Stage 1: Query expansion via Haiku (works — just an LLM call)
- Stage 2: FAISS semantic search on entity/chunk embeddings
  - Option A: Run FAISS in Cloud Run service, rebuild from Firestore embeddings
  - Option B: Use Firestore's native vector search (if region supports it)
  - Option C: Use Vertex AI Vector Search (managed, scales)
- Stage 3: Exact match (works — just string comparison)
- Stage 4: Entity-based chunk boosting (works — just scoring)
- Stage 5: RRF fusion (works — just math)

The blocker is Stage 2: where do the FAISS indexes live in a serverless env?
Best path is probably a persistent Cloud Run service that holds indexes in memory.

**Files**: `orchestrator/src/pipeline/search/` (6 modules), `orchestrator/src/routes/search.py`

## 2. UMAP Layout (Docker Python version)

**Current shortcut**: Upgraded Docker from Python 3.11 → 3.13 to fix numba/UMAP crash.
First `/graph` call on cold start will be slow (~15-30s) loading sentence-transformers + computing UMAP.

**Proper implementation**:
- Pre-compute positions locally or in a batch job, push to Firestore
- Cloud Run only reads stored positions (instant)
- UMAP computation runs as a separate Cloud Run job (triggered when domain count changes)
- Or: pre-seeded universal UMAP model shipped with the app (see umap-layout-design.md)

**Files**: `orchestrator/src/pipeline/domain_layout.py`, `orchestrator/src/routes/graph.py`

## 3. Simmer Pipeline (Not deployed)

**Current shortcut**: General spec manually pushed from local SQLite to Firestore.
No worker service running in cloud — simmer jobs get queued but not executed.
Entity extraction works because we pushed an existing spec.

**Proper implementation**:
- Deploy worker as Cloud Run service with simmer-sdk
- Firebase Function triggers worker via HTTP when job created in Firestore
- Worker runs simmer pipeline (30-50 min), writes results back to Firestore
- Needs: simmer-sdk in Docker image, Firestore-aware worker code

**Files**: `worker/src/`, `functions/index.js`

## 4. Composite Index Avoidance

**Current shortcut**: Several Firestore queries use client-side filter + sort
instead of composite indexes to avoid index creation/management.

**Proper implementation**: Create composite indexes in `firestore.indexes.json`:
- domains: documentCount + path
- jobs: status + createdAt
- specs: domainPath + version
- normalizationQueue: status + similarity

These are one-time setup but we skipped them to move fast.

**File**: `firestore.indexes.json`

## 5. Auth Not Required

**Current shortcut**: `AUTH_REQUIRED=false` on Cloud Run. All API endpoints
are publicly accessible without authentication.

**Proper implementation**: Set `AUTH_REQUIRED=true` once the team management
flow is built. All routes already have auth dependency wired in.

**Files**: `orchestrator/src/auth.py`, Cloud Run env vars

## 6. Single Workspace

**Current shortcut**: All users share `FIREBASE_WORKSPACE_ID=default`.
No workspace isolation, no team management, no invites.

**Proper implementation**: See `docs/multi-tenancy-design.md` for full spec.
Org creation → workspace CRUD → invite flow → workspace selector UI.

**Files**: See multi-tenancy-design.md
