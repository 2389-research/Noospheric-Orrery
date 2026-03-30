# Orrery Firebase Migration — Engineering Reference

*A practical guide for migrating a single-user local app to a hosted, multi-tenant Firebase/GCP system. Written for a data scientist doing their own engineering.*

---

## 1. The Mental Model: How Firebase Works

Firebase is not just a database. It's a platform of services that work together. The key ones for Orrery:

| Service | What it does for you |
|---|---|
| **Firebase Auth** | Manages user identity, issues JWT tokens |
| **Cloud Firestore** | The database — document store with real-time listeners |
| **Firebase Storage** | Blob/file storage (your uploaded docs, simmered specs, FAISS index files) |
| **Cloud Functions** | Short serverless functions triggered by events (≤ 60s jobs) |
| **Cloud Run** | Long-running containerized services (your orchestrator and worker, unchanged) |
| **Eventarc** | The event bus that connects Firestore writes → Cloud Run triggers |

The single most important thing to understand: **Firebase is event-driven.** Instead of polling ("is there work?"), you write a document to Firestore and other services react to it. This replaces your entire SQLite polling loop.

---

## 2. Authentication & Multi-Tenancy

### How Firebase Auth works

Every user gets a signed JWT (ID token) from Firebase. This token is passed with every request. Firestore Security Rules read this token to decide what data that user can access. The token refreshes every hour automatically.

### Custom Claims — the RBAC mechanism

Custom claims are small pieces of data you attach to a user's token server-side. They're available in security rules without a database read, which makes them fast and cheap.

```python
# Server side (Python, Admin SDK) — run this when a user joins an org
from firebase_admin import auth

auth.set_custom_user_claims(user_id, {
    "orgId": "org_abc123",
    "role": "editor"        # admin | editor | viewer
})
```

The claim is then available in every Firestore Security Rule as `request.auth.token.orgId` and `request.auth.token.role`.

**Important caveat:** claims don't update in the client until the token refreshes. For role changes to take effect immediately, force a token refresh from your frontend after setting claims. You can do this by watching for a Firestore document change and calling `user.getIdToken(true)`.

### Multi-tenancy model for Orrery

For 10 users the right model is **Shared Database, Isolated Collections** — one Firebase project, one Firestore database, with all data namespaced under `organizations/{orgId}/workspaces/{workspaceId}/`. This is exactly what your migration spec already describes.

The key principle: **never trust the client to know its own orgId.** Always derive it from the verified JWT claim. A malicious client can't forge a claim because claims are set server-side with the Admin SDK.

```
Firestore Security Rules (conceptual):

match /organizations/{orgId}/workspaces/{workspaceId}/{document=**} {
  // User can only read/write their own org
  allow read: if request.auth.token.orgId == orgId;
  
  // Only editors and admins can write
  allow write: if request.auth.token.orgId == orgId
               && request.auth.token.role in ['editor', 'admin'];
}
```

---

## 3. Firestore — The Database Layer

### Document model vs. relational — what actually changes

Firestore stores JSON documents in collections. There are no joins. This is the core adaptation challenge. The Orrery SQLite schema uses many JOINs, which need to become either:

1. **Denormalized reads** — copy data into the document that needs it, accept duplication
2. **Multiple round-trip reads** — fetch doc A, then use its ID to fetch related doc B
3. **Collection group queries** — query a subcollection across all parent documents

For Orrery specifically:

| Current SQL operation | Firestore equivalent |
|---|---|
| `JOIN domains ON entities.domain = domains.path` | Store `domainPath` on the entity doc; read domain doc separately if needed |
| `JOIN relationships WHERE fromEntity = X` | Query `relationships` collection `where('fromEntity', '==', entityId)` |
| `GROUP BY domain_path COUNT(*)` | Maintain a denormalized `documentCount` field on the domain doc, increment on write |
| `SELECT * FROM jobs WHERE status = 'queued'` | Query `jobs` collection `where('status', '==', 'queued')` — needs a Firestore index |

### Firestore indexes

Firestore automatically indexes every field for simple equality queries. For compound queries (multiple `where` clauses, or `where` + `orderBy`), you need to declare a **composite index** in `firestore.indexes.json`. Firebase CLI will tell you when you're missing one and give you a link to create it.

```json
// firestore.indexes.json
{
  "indexes": [
    {
      "collectionGroup": "jobs",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "workspaceId", "order": "ASCENDING" },
        { "fieldPath": "status", "order": "ASCENDING" },
        { "fieldPath": "createdAt", "order": "DESCENDING" }
      ]
    }
  ]
}
```

### Real-time listeners — replacing your WebSocket

Instead of your FastAPI WebSocket broadcaster, your frontend subscribes directly to Firestore paths. When a document changes, the UI updates automatically with no polling.

```javascript
// Frontend (Next.js) — listen for job status updates
import { onSnapshot, collection, query, where } from 'firebase/firestore';

const q = query(
  collection(db, `organizations/${orgId}/workspaces/${workspaceId}/jobs`),
  where('status', '==', 'running')
);

const unsubscribe = onSnapshot(q, (snapshot) => {
  snapshot.docChanges().forEach((change) => {
    if (change.type === 'modified') {
      updatePipelineUI(change.doc.data());
    }
  });
});

// Clean up when component unmounts
return () => unsubscribe();
```

This is how your simmer progress bars, pipeline status, and entity arrival notifications should all work. No WebSocket, no polling endpoint.

### Firestore document limits

- Max document size: **1 MB**
- Max writes to a single document: ~1/second sustained (Firestore will rate-limit you if you write to the same job doc too fast — use a subcollection for iteration history, which is exactly what your spec already does)
- Entity embeddings (384-dim float32 = ~1.5 KB): fit fine in a document
- UMAP model blob (~50 KB): fits fine
- FAISS index files: **do not store in Firestore** — use Firebase Storage (see section 5)

### The graph snapshot pattern

For the galaxy viz, which loads ~1000 domain/entity reads at once, do not read Firestore directly on every page load. Instead:

1. A Cloud Function triggers whenever a document is ingested or a simmer job completes
2. That function assembles the full graph payload (domains, entities, trade routes) and writes it as a single JSON file to Firebase Storage at a fixed path: `snapshots/{workspaceId}/graph.json`
3. The frontend fetches this one file via a public URL or signed URL

This collapses potentially 1000+ Firestore reads into one HTTP GET. The viz will be ~seconds behind reality, which is perfectly fine.

---

## 4. Event-Driven Pipeline — Replacing the Polling Worker

This is where Firebase really shines for your use case. The entire pipeline becomes a chain of document writes triggering actions.

### The trigger chain

```
User uploads file
    → Frontend writes to Firebase Storage
    → Cloud Function (onObjectCreated trigger)
        → Classifies document (Bedrock call)
        → Writes document record to Firestore (status: 'classified')
        → Writes job doc to jobs/ collection (type: 'extract', status: 'queued')

Job doc written to jobs/ collection
    → Eventarc fires → Cloud Run Worker service
        → Worker picks up job, marks it 'running'
        → Runs extraction pipeline (30-50 min if simmer, 2-10 min if extract_batch)
        → Writes results back to Firestore (entities, relationships)
        → Updates job doc (status: 'completed')

Job doc updated to 'completed'
    → Cloud Function trigger
        → Rebuilds graph snapshot → writes to Firebase Storage
        → Frontend Firestore listener sees job complete → fetches new snapshot → redraws viz
```

### Cloud Functions vs Cloud Run — when to use which

**Cloud Functions (2nd gen):** 
- Triggered by Firestore writes, Storage uploads, Auth events
- Timeout: up to 60 minutes for 2nd gen (but aim for <10 min for anything HTTP-facing)
- Good for: ingest classification, entity extraction, graph snapshot rebuilds, search endpoint
- Cold start: ~2-10s for Python with heavy deps (sentence-transformers = painful). Solution: set `min_instances=1`

**Cloud Run:**
- Always-on containerized services (your existing containers, essentially unchanged)
- No timeout limit — perfect for 30-50 minute simmer jobs
- Can be triggered by Firestore events via Eventarc
- Set `--min-instances=1` on the orchestrator to keep sentence-transformers loaded

```python
# Cloud Function (Python) — triggered when a job document is created
from firebase_functions.firestore_fn import on_document_created, Event, DocumentSnapshot
from firebase_admin import firestore

@on_document_created(document="organizations/{orgId}/workspaces/{workspaceId}/jobs/{jobId}")
def on_job_created(event: Event[DocumentSnapshot]) -> None:
    job_data = event.data.to_dict()
    
    if job_data['type'] in ['simmer_general', 'simmer_domain']:
        # Dispatch to Cloud Run worker via HTTP or Pub/Sub
        dispatch_to_worker(job_data)
    elif job_data['type'] == 'extract_batch':
        # Can run directly in the function if < 60 min
        run_extraction(job_data)
```

### Dispatching long jobs to Cloud Run

For simmer jobs that run 30-50 min, you can't run them in a Cloud Function. Two good patterns:

**Option A: Pub/Sub** (recommended for reliability)
```
Cloud Function writes job doc → also publishes to Pub/Sub topic
Cloud Run Worker subscribes to topic → picks up message → runs job
```

**Option B: Cloud Tasks** (good for retry control, scheduling)
```
Cloud Function writes job doc → enqueues Cloud Task with job payload
Cloud Task calls Cloud Run Worker HTTP endpoint → runs job
```

Pub/Sub is simpler to set up. Cloud Tasks gives you more control over retries, rate limiting, and scheduling. For Orrery at 10 users, Pub/Sub is fine.

---

## 5. FAISS on Cloud Run — The Vector Search Service

### Architecture

Run FAISS as a **persistent Cloud Run service** (not a job — a long-running service). Set `--min-instances=1` so it never cold-starts. The service:

1. On startup: downloads FAISS index files from Firebase Storage, loads them into memory
2. Serves search requests as a simple FastAPI HTTP endpoint
3. When new entities are embedded: receives the new vectors, updates the in-memory index, periodically persists back to Firebase Storage

```python
# faiss_service/main.py (simplified)
from fastapi import FastAPI
from google.cloud import storage
import faiss, numpy as np, pickle

app = FastAPI()

# Load indexes from Cloud Storage on startup
def load_indexes():
    client = storage.Client()
    bucket = client.bucket("your-bucket")
    
    # Download index binary
    blob = bucket.blob(f"faiss/{workspace_id}/entity.index")
    blob.download_to_filename("/tmp/entity.index")
    
    # Load into memory
    index = faiss.read_index("/tmp/entity.index")
    return index

entity_index = load_indexes()

@app.post("/search")
async def search(query_vector: list[float], top_k: int = 10):
    vec = np.array([query_vector], dtype=np.float32)
    distances, indices = entity_index.search(vec, top_k)
    return {"indices": indices[0].tolist(), "distances": distances[0].tolist()}

@app.post("/add")
async def add_vectors(vectors: list[list[float]], ids: list[int]):
    vecs = np.array(vectors, dtype=np.float32)
    entity_index.add_with_ids(vecs, np.array(ids))
    # Async: periodically flush back to Cloud Storage
    return {"added": len(vectors)}
```

### Index persistence pattern

FAISS has no built-in persistence. The pattern for Cloud Run:

1. On startup: `faiss.read_index()` from a file downloaded from Cloud Storage
2. In memory: serve all search/add requests from the live index
3. Periodically (or after N additions): `faiss.write_index()` then upload to Cloud Storage
4. On crash/restart: reload from Cloud Storage (you lose at most one flush window of additions)

For workspace isolation: one FAISS index per workspace, stored at `faiss/{workspaceId}/entity.index` and `faiss/{workspaceId}/chunk.index` in Firebase Storage.

### Cloud Storage FUSE (alternative)

Cloud Run supports mounting a Cloud Storage bucket as a local filesystem via FUSE. This means the index file appears as a local file to your container without explicit download/upload code. However: FUSE is slower than RAM, doesn't support concurrent writes, and adds latency. For a read-heavy search service, explicit load-on-startup is cleaner.

---

## 6. Firebase Storage — Files and Blobs

Firebase Storage (backed by Google Cloud Storage) handles everything that doesn't fit in Firestore:

| What | Path |
|---|---|
| Uploaded documents | `orgs/{orgId}/workspaces/{workspaceId}/docs/{docId}/original.md` |
| Simmered specs | `orgs/{orgId}/workspaces/{workspaceId}/specs/{domainPath}/v{n}.json` |
| Golden sets | `orgs/{orgId}/workspaces/{workspaceId}/specs/{domainPath}/golden.json` |
| FAISS indexes | `faiss/{workspaceId}/entity.index` |
| UMAP model | `umap/{workspaceId}/model.pkl` |
| Graph snapshots | `snapshots/{workspaceId}/graph.json` |

Storage security rules work the same way as Firestore rules — you gate access by the JWT token's orgId claim.

### Triggering ingest from a file upload

When a user uploads a document via the frontend, the frontend writes directly to Firebase Storage. This fires a Cloud Function:

```python
from firebase_functions import storage_fn

@storage_fn.on_object_created(bucket="your-bucket")
def on_document_uploaded(event: storage_fn.CloudEvent):
    file_path = event.data.name  # e.g. "orgs/abc/workspaces/xyz/docs/doc123/original.md"
    # Parse the path to get orgId, workspaceId, docId
    # Kick off ingest pipeline
```

This completely replaces your current upload endpoint — no FastAPI route needed for file ingestion.

---

## 7. The DB Abstraction Layer Strategy

Rather than rewriting all your routes at once, build a thin interface that both SQLite and Firestore can implement. This lets you run both backends in parallel and flip between them.

```python
# db/interface.py
from abc import ABC, abstractmethod

class OrreryDB(ABC):
    
    @abstractmethod
    async def get_document(self, workspace_id: str, doc_id: str) -> dict: ...
    
    @abstractmethod
    async def create_job(self, workspace_id: str, job: dict) -> str: ...
    
    @abstractmethod
    async def update_job_status(self, workspace_id: str, job_id: str, status: str): ...
    
    @abstractmethod
    async def get_domains(self, workspace_id: str) -> list[dict]: ...
    
    @abstractmethod
    async def upsert_entity(self, workspace_id: str, entity: dict) -> str: ...
    
    # ... etc

# db/sqlite_impl.py — your current code, wrapped
class SQLiteDB(OrreryDB):
    async def get_document(self, workspace_id, doc_id):
        # existing SQL query
        ...

# db/firestore_impl.py — the new implementation
class FirestoreDB(OrreryDB):
    async def get_document(self, workspace_id, doc_id):
        doc = await self.fs.collection(f"...workspaces/{workspace_id}/documents").document(doc_id).get()
        return doc.to_dict()
```

Then in your routes:
```python
# Inject via config, not hardcoded
db: OrreryDB = FirestoreDB() if os.getenv("USE_FIRESTORE") else SQLiteDB()
```

This is the safest migration path. You can run both in staging simultaneously and diff the outputs.

---

## 8. The simmer-sdk File I/O Problem

Currently simmer-sdk reads and writes judgment files to disk. In Cloud Run this is fine — you have ephemeral `/tmp` storage (backed by RAM, max 32 GB). The issue is persistence across restarts.

**Solution:** After each simmer phase, copy judgment files and spec artifacts from `/tmp/` to Firebase Storage. On job startup, check if there's a checkpoint in Storage and resume from there.

This also gives you crash recovery — if a 45-minute simmer job dies at minute 40, it can resume from the last checkpoint rather than starting over.

---

## 9. Cost Model for 10 Users

Rough estimate for light-to-moderate usage:

| Service | Cost driver | Estimated monthly |
|---|---|---|
| Cloud Firestore | ~50K reads/day (mostly cached by snapshot), ~5K writes/day | ~$5-15 |
| Firebase Storage | ~1 GB stored, ~10 GB egress | ~$2-5 |
| Cloud Run (orchestrator, min=1) | 1 instance always on | ~$15-30 |
| Cloud Run (worker, min=0) | Only runs during simmer/extract jobs | ~$5-20 depending on usage |
| Cloud Functions | Triggered on events, short-lived | ~$1-3 |
| **Total** | | **~$25-75/month** |

The graph snapshot pattern is critical here — it collapses the most expensive Firestore read pattern (1000 reads per viz load) into nearly zero cost.

---

## 10. Migration Sequence (Practical Order)

### Step 1: Infrastructure first (1-2 days)
- Create Firebase project
- Enable Firestore (Native mode), Firebase Auth, Firebase Storage
- Deploy frontend to Vercel with Firebase Auth added (Google sign-in is the easiest start)
- Keep orchestrator running locally or on your current machine — just add auth token validation middleware to FastAPI
- Verify you can sign in and get a valid JWT

### Step 2: Build the DB abstraction layer (2-3 days)
- Write the `OrreryDB` interface against your existing routes
- Wrap existing SQLite code in `SQLiteDB` implementation
- All routes now go through the interface — behavior unchanged, you've just added indirection
- Test thoroughly — this is the safety net for everything that follows

### Step 3: Implement `FirestoreDB` (3-5 days)
- Implement each method in the interface against Firestore
- Translate the most complex queries first (graph endpoint, search, job management)
- Run both backends side by side with integration tests comparing outputs
- The `JOIN` → denormalization work happens here

### Step 4: Migrate compute to Cloud Run (1-2 days)
- Deploy orchestrator container to Cloud Run (min=1)
- Deploy worker container to Cloud Run (min=0)
- Connect Eventarc: Firestore job writes → trigger worker
- Verify end-to-end pipeline with Firestore backend

### Step 5: FAISS service (1 day)
- Extract FAISS into its own Cloud Run service
- Implement startup-load from Firebase Storage, periodic flush back
- Wire orchestrator to call FAISS service for search

### Step 6: Graph snapshot + Storage triggers (1 day)
- Implement graph snapshot Cloud Function
- Frontend reads from Storage snapshot instead of calling `/graph`
- File upload → Storage → Cloud Function ingest trigger

### Step 7: Multi-workspace UI (1-2 days)
- Workspace selector in frontend
- Per-workspace Firestore paths everywhere

---

## 11. Key Gotchas

**Firestore composite indexes:** You will hit "missing index" errors the first time you run a compound query. Firebase will log the exact URL to create the index. Add it to `firestore.indexes.json` and commit it. Don't create indexes manually in the console — they won't be in version control.

**Custom claims don't update immediately:** After `set_custom_user_claims()`, the client token is stale for up to 1 hour. Force refresh with `user.getIdToken(true)` on the client after any role/org change.

**Eventarc at-least-once delivery:** Firestore triggers can fire more than once for the same event (rare but real). Make your job handlers idempotent — check if the job is already `running` or `completed` before starting work.

**Cloud Run `/tmp` is RAM:** `45 GiB` max container memory, but `/tmp` counts against it. For simmer jobs that write large judgment files, budget accordingly. A 4 GB container with heavy `/tmp` usage needs more memory allocated, not just disk.

**Firestore Security Rules bypass:** The Admin SDK (used in Cloud Run/Cloud Functions) bypasses all security rules. Rules only apply to client SDK calls. This is correct behavior — your backend should use the Admin SDK and be trusted. But it means rule bugs don't protect you from backend bugs.

**document IDs:** Don't use sequential integers or monotonically increasing IDs. Firestore distributes data by key prefix and hot-spotting will throttle you. Use Firebase's auto-generated IDs (`db.collection('...').document()` without arguments generates a good random ID) or UUIDs.
