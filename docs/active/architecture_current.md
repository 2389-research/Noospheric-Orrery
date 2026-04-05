# Noospheric Orrery — Current Architecture

*Living document. Describes the system as deployed on the `firebase-migration`
branch as of 2026-04-03.*

---

## System Overview

Three services + one trigger function:

```
┌─────────────┐     ┌───────────────┐     ┌──────────────┐
│  Frontend    │────▶│  Orchestrator │◀───▶│   Firestore   │
│  (Next.js)  │     │  (FastAPI)    │     │  (or SQLite)  │
└─────────────┘     └───────┬───────┘     └──────┬────────┘
                            │                     │
                    ┌───────▼───────┐     ┌──────▼────────┐
                    │    Worker     │     │ Cloud Function │
                    │ (Cloud Run   │◀────│ (Firestore     │
                    │   Job)       │     │  trigger)      │
                    └──────────────┘     └───────────────┘
```

- **Orchestrator**: REST API. Classification, extraction, search, graph.
- **Worker**: Long-running jobs — simmering, batch extraction, post-processing.
- **Frontend**: Next.js with Firebase Auth. Proxies API via rewrites.
- **Cloud Function**: Watches Firestore for new jobs, triggers Cloud Run.

---

## Multi-Tenancy Model

```
organizations/{orgId}
  name, createdAt, createdBy
  members/{userId}
    role: admin | editor | viewer
    email, joinedAt

workspaces/{workspaceId}           ← ALL data scoped here
  orgId, name, description, status
  documents/{docId}
  entities/{entityId}
  domains/{domainPathEncoded}
  jobs/{jobId}
  specs/{specId}
  entitySources/{sourceId}
  relationships/{relId}
  chunks/{chunkId}
  documentDomains/{assignmentId}
  domainLayout/{pathEncoded}
  simmerIterations/{iterId}
  simmerCriterionDetails/{detailId}
  cache/graph                      ← precomputed viz JSON

invites/{inviteId}                 ← top-level
users/{userId}                     ← token refresh sentinel
```

### Auth Flow

1. User signs in with Google (Firebase Auth popup)
2. Frontend calls `POST /auth/accept-invite` (checks for pending invite)
3. Frontend calls `POST /auth/provision` (creates org + workspace if new)
4. Backend sets JWT custom claims: `{orgId, role}`
5. Every API call includes `Authorization: Bearer <token>` + `X-Workspace-Id`
6. Backend validates workspace belongs to user's org

### Role Hierarchy

| Role | Level | Can do |
|------|-------|--------|
| admin | 3 | Everything + manage team, workspaces, invites |
| editor | 2 | Upload, trigger pipeline, resolve reviews |
| viewer | 1 | Browse entities, view orrery, search |

---

## Repository Pattern

All data access goes through abstract interfaces. Two implementations:

```python
DataStore
  ├── SQLiteDataStore     (DB_BACKEND=sqlite)
  └── FirestoreDataStore  (DB_BACKEND=firestore)
```

### Interfaces

| Repository | Key Methods |
|---|---|
| DocumentRepository | create, get, list, get_by_hash, update_status, get_for_domain |
| ChunkRepository | create_batch, get_for_document |
| DomainRepository | create, get, list, get_all_paths, assign_document, get_entity_domain_weights |
| EntityRepository | create, get, get_by_name, list, update_embedding |
| EntitySourceRepository | create, get_for_entity, get_source_count, update_entity_id |
| RelationshipRepository | upsert_cooccurrence, get_cooccurrences, get_star_graph, get_trade_routes |
| JobRepository | create, get, list, get_existing, pick_next, mark_running/completed/failed |
| SpecRepository | create, get_general, get_for_domain |
| NormalizationRepository | create_review, get_review_queue, resolve_review, get_merge_history |
| LayoutRepository | get_stored_positions, store_position, store_model |
| SimmerIterationRepository | create_iteration, create_criterion_detail, get_for_job |

### What's Generic vs Firebase-Specific

**Generic (works with any backend implementing the interfaces):**
- All route handlers (use `store.*` methods)
- All pipeline functions (chunker, classifier, extractor, normalizer, etc.)
- LLM calls via `orrery_relay.Relay`
- Job dispatch pattern (create job → worker picks up)

**Firebase/Google-specific (would need adapters for other providers):**

| Component | Firebase/Google Service | Interface | Portable Alternative |
|---|---|---|---|
| Auth token verification | `firebase_admin.auth.verify_id_token()` | JWT validation | Any JWT issuer (Auth0, Cognito, Supabase) |
| Custom claims | `firebase_admin.auth.set_custom_user_claims()` | Write claims to JWT | Store role in DB, include in JWT at sign-in |
| Token refresh signal | Firestore `users/{uid}/tokenRefreshAt` sentinel doc | Real-time notification | WebSocket push, SSE, polling |
| Firestore queries | `collection.where().stream()` | Document queries | Any document DB (MongoDB, DynamoDB, Postgres JSONB) |
| Firestore vector search | `collection.find_nearest()` | Vector similarity | pgvector, Pinecone, Qdrant, local FAISS |
| Firestore real-time | `onSnapshot()` in frontend hooks | Live updates | WebSocket, SSE, polling |
| Vertex AI embeddings | `genai.Client.embed_content()` | Text → vector | OpenAI embeddings, sentence-transformers, Cohere |
| Cloud Run Jobs | `gcloud run jobs execute` | Background job execution | Celery, Bull, SQS+Lambda, local subprocess |
| Cloud Functions | Firestore trigger → dispatch | Event-driven trigger | Webhook, DB trigger, polling worker |
| Firebase Auth (frontend) | `signInWithPopup(GoogleAuthProvider)` | OAuth sign-in | Any OAuth provider SDK |
| Firestore Security Rules | `firestore.rules` | Client-side access control | Backend-only validation (no client SDK) |

### Key Observation for Local Mode

The Firebase-specific pieces fall into categories:

1. **Auth** — Can be replaced with noop (always authenticated, admin role). Already exists as `DEV_USER` when `AUTH_REQUIRED=false`.
2. **Storage** — Already has SQLite adapter via repository pattern.
3. **Embeddings** — sentence-transformers fallback exists (moved to `[local]` optional dep).
4. **Search** — FAISS fallback exists for SQLite mode.
5. **Job execution** — SQLite worker polls the DB directly (no Cloud Function needed).
6. **Real-time updates** — Frontend hooks would use REST polling instead of `onSnapshot`.

The **only new adapter needed** for full local mode is a noop auth provider on the frontend (`NEXT_PUBLIC_AUTH_MODE=noop`).

---

## API Endpoints

### Ingest & Documents
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | /ingest | editor+ | Upload file, classify, extract |
| POST | /ingest/directory | editor+ | Ingest directory recursively |
| GET | /documents | viewer+ | List documents |
| GET | /documents/{id} | viewer+ | Get document with content |
| GET | /documents/{id}/reader | viewer+ | Get document with entity spans |

### Entities
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | /entities | viewer+ | List entities (filterable) |
| GET | /entities/{id} | viewer+ | Entity detail with sources |
| GET | /entities/{id}/cooccurrences | viewer+ | Co-occurring entities |
| GET | /entities/{id}/star-graph | viewer+ | Full entity connection graph |

### Domains & Graph
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | /domains | viewer+ | Domain taxonomy with counts |
| GET | /graph | viewer+ | Precomputed graph JSON for orrery |
| GET | /graph/umap | viewer+ | Graph with UMAP layout |
| GET | /stats | viewer+ | Summary counts |

### Pipeline
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | /simmer/general | editor+ | Trigger general spec simmering |
| POST | /simmer/{domain} | editor+ | Trigger domain-specific simmering |
| POST | /normalize | editor+ | Trigger entity normalization |
| GET | /normalize/summary | viewer+ | Normalization stats |
| GET | /normalize/review | viewer+ | Pending review queue |
| POST | /normalize/review/{id} | editor+ | Resolve review |
| POST | /discover-subdomains | editor+ | Discover new subdomains |
| POST | /reclassify | editor+ | Re-classify all documents |

### Search
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | /search | viewer+ | Vector search + expansion |
| POST | /search/rebuild | editor+ | Rebuild search indexes |

### Jobs
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | /jobs | viewer+ | List jobs |
| GET | /jobs/{id}/iterations | viewer+ | Simmer iteration history |

### Auth & Multi-Tenancy
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | /auth/provision | authenticated | Create/return org + workspaces |
| POST | /auth/accept-invite | authenticated | Claim pending invite |
| POST | /invites | admin | Create invite |
| GET | /invites | admin | List pending invites |
| DELETE | /invites/{id} | admin | Revoke invite |
| POST | /workspaces | admin | Create workspace |
| GET | /workspaces | viewer+ | List org workspaces |
| PATCH | /workspaces/{id} | admin | Rename workspace |
| DELETE | /workspaces/{id} | admin | Archive workspace |

---

## Worker Job Types

All dispatched via Cloud Function on Firestore job doc creation.

| Job Type | Target | Purpose | Chain |
|---|---|---|---|
| simmer_general | "general" | Parent — kicks off golden set | → simmer_golden_set |
| simmer_golden_set | "general" | Refine entity taxonomy | → simmer_extraction_spec |
| simmer_extraction_spec | "general" | Refine extraction prompt | → extract_batch |
| simmer_domain | domain_path | Parent — kicks off domain golden set | → simmer_domain_golden_set |
| simmer_domain_golden_set | domain_path | Domain-specific golden set | → simmer_domain_extraction_spec |
| simmer_domain_extraction_spec | domain_path | Domain-specific extraction prompt | Saves spec, marks domain |
| extract_batch | "general" or domain | Extract entities + run post_process | |
| post_process | "general" | Embed → cooccurrences → UMAP → graph cache | |

### Job Chain (General Simmer)

```
simmer_general (parent, stays running)
  └→ simmer_golden_set (child, fresh container)
       └→ simmer_extraction_spec (child, fresh container)
            └→ extract_batch (auto-queued)
                 └→ post_process (embedded in extract_batch)
```

Iterations from both phases written to parent job ID for unified UI.

---

## Pipeline Functions

| File | Purpose | LLM? |
|---|---|---|
| chunker.py | Split doc into chunks | No |
| excerpt.py | Build classification excerpt | No |
| classifier.py | Classify into domains | Yes — `relay.complete_structured()` |
| domain_normalizer.py | Assign domains, create hierarchy | No |
| extractor.py | Extract entities from chunks | Yes — `relay.complete_structured()` |
| normalizer.py | Dedup entities by name+type | No |
| embedding_normalizer.py | Similarity-based entity merging | Vertex AI embeddings |
| cooccurrence.py | Compute entity co-occurrence edges | No |
| subdomain_discovery.py | Discover subdomains from entities | Yes — `relay.complete_structured()` |
| domain_layout.py | UMAP layout for viz (SQLite only) | Vertex AI embeddings |
| search/expansion.py | Query expansion | Yes — `relay.complete_structured()` |
| search/retrieval.py | FAISS search (SQLite only) | sentence-transformers |
| search/entity_boost.py | Boost entities by source count | No |
| search/fusion.py | Rank fusion across retrievers | No |

All LLM calls use `relay.complete_structured()` with tool use schemas —
guaranteed valid JSON, no parsing fallbacks.

---

## Environment Variables

### Core
| Var | Default | Purpose |
|---|---|---|
| DB_BACKEND | sqlite | "sqlite" or "firestore" |
| AUTH_REQUIRED | false | Force auth even on SQLite |
| ANTHROPIC_BACKEND | gateway | "gateway" or "bedrock" |
| CLASSIFICATION_MODEL | claude-sonnet-4-6 | Model for classification |
| EXTRACTION_MODEL | claude-haiku-4-5 | Model for extraction |

### AWS/Bedrock
| Var | Purpose |
|---|---|
| AWS_ACCESS_KEY | Bedrock credentials |
| AWS_SECRET_KEY | Bedrock credentials |
| AWS_REGION | us-east-1 |
| GATEWAY_URL | Bedrock Gateway proxy URL |
| GATEWAY_API_KEY | Gateway auth |

### Firebase/Google
| Var | Purpose |
|---|---|
| FIREBASE_PROJECT_ID | noospheric-orrery |
| FIREBASE_WORKSPACE_ID | Default workspace ID |
| GOOGLE_APPLICATION_CREDENTIALS | Service account path |
| VERTEX_AI_REGION | us-central1 |

### Frontend (NEXT_PUBLIC_*)
| Var | Purpose |
|---|---|
| NEXT_PUBLIC_FIREBASE_API_KEY | Firebase client config |
| NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN | Firebase client config |
| NEXT_PUBLIC_FIREBASE_PROJECT_ID | Firebase client config |
| NEXT_PUBLIC_MAGOS_WORKSPACE_ID | Demo workspace ID |
| BACKEND_URL | Next.js API rewrite target |

### Processing
| Var | Default | Purpose |
|---|---|---|
| CHUNK_SIZE | 2000 | Document chunk size |
| GENERAL_SPEC_THRESHOLD | 10 | Min docs before auto-simmer |
| DOMAIN_SPEC_THRESHOLD | 20 | Min domain docs before simmer |
| SIMMER_ITERATIONS | 5 | Iterations per simmer phase |

---

## Deployment

### Cloud Run (Orchestrator)
- Image: `orrery-orchestrator:v12-structured` (333MB)
- Port: 8000
- Memory: 1GB, CPU: 1
- No CUDA/torch (moved to `[local]` optional deps)

### Cloud Run Job (Worker)
- Image: `simmer-worker:v10-score-fix` (1.09GB)
- Includes Node.js + Claude CLI (for simmer-sdk judge board)
- Timeout: 2 hours
- Memory: 4GB, CPU: 4

### Firebase App Hosting (Frontend)
- Auto-deploys from `firebase-migration` branch
- Env vars in `apphosting.yaml`
- Next.js rewrites `/api/*` → orchestrator

### Cloud Function
- `onJobCreated` — Firestore trigger on job doc creation
- Dispatches Cloud Run Job with `JOB_ID` + `WORKSPACE_ID` env vars
