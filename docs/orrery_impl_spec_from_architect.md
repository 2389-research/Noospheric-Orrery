# Orrery — Implementation Spec
## Embeddings · Vector Search · Simmer Worker · Multi-Tenancy

*Research-backed skeleton for the implementation agent. Each section documents
what to build, exact libraries and APIs to use, working code patterns, and
known gotchas. The agent adds the muscle (wiring into existing repo structure,
env vars, error handling, tests).*

---

## Part 1: Embedding Service

### Decision: Cloud Run service with baked model image

**Not a Firebase Function.** Firebase Functions v2 Python uses Google Cloud
Buildpacks, not a real Dockerfile, which makes baking a 90MB model file into
the image awkward. Cloud Run uses a real Dockerfile. Same HTTP API surface —
if we ever want to switch hosting, the orchestrator call doesn't change.

Deploy as a standalone Cloud Run service with `--min-instances=1`. Model loads
once on startup and stays warm. Cold start with baked image is ~3-5s. Cold
start with runtime download from HuggingFace is 10-15s.

The upgrade path to always-warm is just `--min-instances=1`, which the
orchestrator already has. Prototype without it, add it if cold starts hurt.

### Proactive warming

On the frontend, fire a fire-and-forget ping to the embedding service whenever
a user signs in or navigates to the upload page. The orchestrator exposes a
lightweight `/internal/warm` endpoint that just calls the embedding service
with a dummy text and discards the result. Frontend never calls the embedding
service directly.

---

### 1.1 Dockerfile

```dockerfile
# embedding_service/Dockerfile
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install deps first (cached layer if requirements.txt unchanged)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake model into image at build time.
# SentenceTransformer caches to ~/.cache/huggingface/hub by default.
# This RUN layer downloads and saves the weights into the image.
# No network call happens at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; \
               SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

# Cloud Run sets PORT env var. Single worker — Cloud Run scales by instances.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

```
# embedding_service/requirements.txt
fastapi
uvicorn
sentence-transformers==3.x   # pin to whatever is current stable
torch                         # CPU-only — add --index-url for CPU wheel if needed
numpy
```

> **Note on torch size:** The full torch wheel is ~700MB. For CPU-only inference
> use the CPU-specific wheel: `torch --index-url https://download.pytorch.org/whl/cpu`.
> This drops the image to ~1.2GB total vs ~2.5GB. Add `--platform linux/amd64`
> to the build command if building on Apple Silicon.

---

### 1.2 FastAPI service

```python
# embedding_service/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from typing import Optional
import numpy as np
import logging

logger = logging.getLogger("embedding_service")
app = FastAPI()

# Module-level — loaded once, survives across requests while instance is warm.
# model.encode() is not thread-safe in older versions; use convert_to_numpy=True
# and avoid concurrent requests to the same encode call.
# For Orrery's request volume this is fine. Add a threading.Lock if needed.
_model: Optional[SentenceTransformer] = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Model loaded.")
    return _model

# Load model on startup so first request isn't slow
@app.on_event("startup")
async def startup():
    get_model()

class EmbedRequest(BaseModel):
    texts: list[str]
    normalize: bool = True   # all-MiniLM-L6-v2 benefits from L2 normalization

class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    dim: int

@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    if not req.texts:
        raise HTTPException(400, "texts must be non-empty")
    model = get_model()
    vecs = model.encode(
        req.texts,
        normalize_embeddings=req.normalize,  # True → unit vectors → use DOT_PRODUCT in Firestore
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return EmbedResponse(embeddings=vecs.tolist(), dim=vecs.shape[1])

@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _model is not None}
```

---

### 1.3 Deploy command

```bash
# Build and push to Artifact Registry
PROJECT_ID="your-project-id"
REGION="us-central1"
REPO="orrery"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/embedding-service:latest"

docker build --platform linux/amd64 -t $IMAGE ./embedding_service
docker push $IMAGE

# Deploy to Cloud Run
# --min-instances=0 for prototype (accept occasional cold start)
# --min-instances=1 for always-warm (~$15-30/mo for smallest instance)
gcloud run deploy embedding-service \
  --image=$IMAGE \
  --region=$REGION \
  --memory=2Gi \
  --cpu=1 \
  --concurrency=4 \
  --min-instances=0 \
  --max-instances=3 \
  --no-allow-unauthenticated \
  --project=$PROJECT_ID
```

> **Authentication:** `--no-allow-unauthenticated` means only services with
> the `roles/run.invoker` IAM role can call it. The orchestrator's Cloud Run
> service account gets this role. The embedding service is never exposed to
> the public internet.

---

### 1.4 Calling from orchestrator

The orchestrator calls the embedding service via HTTP using the service's
internal Cloud Run URL. Within GCP, Cloud Run services can call each other
using the metadata server to get an identity token.

```python
# orchestrator/src/services/embedding.py
import os
import httpx
import google.auth.transport.requests
import google.oauth2.id_token

EMBEDDING_SERVICE_URL = os.environ["EMBEDDING_SERVICE_URL"]
# e.g. https://embedding-service-xxxx-uc.a.run.app

def _get_id_token(audience: str) -> str:
    """Gets a Google-signed ID token for Cloud Run service-to-service auth."""
    request = google.auth.transport.requests.Request()
    return google.oauth2.id_token.fetch_id_token(request, audience)

async def embed_texts(texts: list[str], normalize: bool = True) -> list[list[float]]:
    token = _get_id_token(EMBEDDING_SERVICE_URL)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{EMBEDDING_SERVICE_URL}/embed",
            json={"texts": texts, "normalize": normalize},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]
```

**Dependency:** `google-auth`, `httpx` — both already in most Python Cloud
Run setups. The `google.oauth2.id_token.fetch_id_token` call hits the metadata
server automatically when running on GCP.

---

### 1.5 UMAP integration

UMAP transform lives in the orchestrator (or a Cloud Function), not in the
embedding service. The flow:

1. Build domain text string: `"{domain_path}. {top 6 doc titles}. {top 12 entity names}"`
2. Call embedding service → get 384-dim vector
3. Load pickled UMAP model from Firestore `layoutModel/umap` doc (bytes field)
4. `reducer.transform([embedding_vector])` → `[[x, y]]`
5. Normalize x, y to [0,1] range
6. Write position to domain doc

**Future UMAP note:** The current fit-on-corpus approach has first-mover bias.
The long-term plan is to train a universal UMAP model offline on a large,
diverse set of embeddings spanning many domains (science, business, law, fiction,
history, etc.), ship that as the default `layoutModel`, and have all workspaces
call `transform()` only — never `fit()`. This makes domain placement
deterministic and comparable across workspaces, and eliminates the need to
re-fit when domain count doubles. This is a data science task done once
outside of Orrery's deployment pipeline.

---

## Part 2: Firestore Vector Search

### Overview

No separate service. Embeddings stored as vector fields on entity and chunk
docs. Firestore's `find_nearest()` replaces FAISS for retrieval. Exact KNN
(flat index) is fine for <10K vectors — Firestore handles it efficiently.

### 2.1 Distance measure

`all-MiniLM-L6-v2` with `normalize_embeddings=True` produces **unit vectors
(L2-normalized)**. For unit vectors, Google recommends `DOT_PRODUCT` — it is
mathematically equivalent to cosine similarity but faster. Use `DOT_PRODUCT`
throughout.

- `DOT_PRODUCT` distance ranges: higher = more similar (unlike COSINE where lower = more similar)
- For unit vectors: `dot_product = cosine_similarity` exactly
- Use `COSINE` if unsure whether embeddings are normalized

---

### 2.2 Schema changes

Add an `embedding` vector field to entity and chunk documents. Firestore
stores these as a native vector type — not bytes, not a list — using
`firestore.SERVER_TIMESTAMP`-style magic.

```python
from google.cloud.firestore_v1.vector import Vector

# Writing an embedding — use Vector() wrapper
entity_ref.update({
    "embedding": Vector(embedding_list),   # list[float], 384 elements
})
```

---

### 2.3 Index creation

Vector indexes must be created via `gcloud` before `find_nearest()` works.
Firestore will log the exact error message + command when you first hit a
missing index in logs — but it's better to create them upfront.

```bash
# Entity embedding index
gcloud firestore indexes composite create \
  --project=YOUR_PROJECT_ID \
  --collection-group=entities \
  --query-scope=COLLECTION \
  --field-config=vector-config='{"dimension":"384","flat":"{}"}',field-path=embedding

# Chunk embedding index
gcloud firestore indexes composite create \
  --project=YOUR_PROJECT_ID \
  --collection-group=chunks \
  --query-scope=COLLECTION \
  --field-config=vector-config='{"dimension":"384","flat":"{}"}',field-path=embedding
```

> **Dimension must match exactly.** `all-MiniLM-L6-v2` = 384 dimensions.
> If you ever switch models, you must delete and recreate indexes AND
> re-embed all entities/chunks.

Store these commands in `scripts/create_indexes.sh` and check into the repo.
Do not create indexes manually through the console — they won't survive
a project recreation.

---

### 2.4 Query pattern

```python
# orchestrator/src/pipeline/search/retrieval.py (new version)
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector

async def search_entities(
    db,
    workspace_id: str,
    query_embedding: list[float],
    top_k: int = 20,
) -> list[dict]:
    """Vector search on entities collection."""
    collection = db.collection(f"workspaces/{workspace_id}/entities")
    results = collection.find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_embedding),
        distance_measure=DistanceMeasure.DOT_PRODUCT,
        limit=top_k,
    ).get()

    return [
        {
            "id": doc.id,
            **doc.to_dict(),
            # DOT_PRODUCT: higher = more similar. Invert for scoring.
            "score": doc.get("distance") or 0.0,
        }
        for doc in results
    ]

async def search_chunks(
    db,
    workspace_id: str,
    query_embedding: list[float],
    top_k: int = 20,
) -> list[dict]:
    """Vector search on chunks collection."""
    collection = db.collection(f"workspaces/{workspace_id}/chunks")
    results = collection.find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_embedding),
        distance_measure=DistanceMeasure.DOT_PRODUCT,
        limit=top_k,
    ).get()
    return [{"id": doc.id, **doc.to_dict()} for doc in results]
```

> **Note on distance field:** Firestore's Python SDK returns the distance as
> a separate field accessible via a special attribute, not inside `to_dict()`.
> Check the SDK version's docs for how to read the computed distance —
> in recent versions it appears in the document data under a key you specify
> with `distance_result_field`. Confirm the exact API with the installed
> version of `google-cloud-firestore`.

---

### 2.5 Updated search pipeline wiring

The existing 6-module search pipeline in `orchestrator/src/pipeline/search/`
stays structurally the same. Only `retrieval.py` changes — replace the FAISS
index lookup with `find_nearest()` calls. Query expansion (Haiku), entity
boosting, and RRF fusion are unchanged.

```
search/pipeline.py        ← unchanged entry point
search/expansion.py       ← unchanged (Haiku query expansion)
search/retrieval.py       ← REPLACE FAISS with find_nearest()
search/entity_boost.py    ← unchanged
search/fusion.py          ← unchanged (RRF)
search/models.py          ← unchanged
search/config.py          ← unchanged
```

The orchestrator's `/search` route calls `embed_texts()` to get the query
embedding before calling `search_entities()` and `search_chunks()`.

---

### 2.6 Backfill

One-time job after deploying the embedding service. Two options:

**Option A — Cloud Run Job (recommended for large corpora)**

Write a standalone `backfill.py` script that:
1. Pages through all entity docs in Firestore (use `stream()` with a limit)
2. Collects docs without an `embedding` field
3. Batches texts → calls embedding service → writes `Vector(embedding)` back
4. Same for chunks

Deploy as a Cloud Run Job, run once, done.

```bash
gcloud run jobs create backfill-embeddings \
  --image=YOUR_ORCHESTRATOR_IMAGE \
  --command=python \
  --args=scripts/backfill_embeddings.py \
  --region=us-central1 \
  --set-env-vars=EMBEDDING_SERVICE_URL=...,FIRESTORE_PROJECT=...
gcloud run jobs execute backfill-embeddings --region=us-central1
```

**Option B — run locally against prod Firestore**

If the entity/chunk count is small, run the backfill script locally with
`GOOGLE_APPLICATION_CREDENTIALS` set to a service account key. Simpler,
no Cloud Run Job setup needed.

Keep keyword search (`contains`) as a fallback during backfill — run both,
merge results. Only flip to pure vector search after backfill is confirmed
complete.

---

## Part 3: Simmer Worker (Cloud Run Job)

### Overview

The worker is a Cloud Run **Job** (not a Service). It runs on demand, exits
when done, and you pay only for runtime. The trigger chain:

```
Orchestrator creates job doc in Firestore (status: "queued")
    → Firestore triggers a lightweight Cloud Function
        → Cloud Function calls Cloud Run Jobs API to start execution
            → Job reads job_id from env, fetches doc, runs simmer pipeline
                → Writes results to Firestore, marks job "completed"
```

---

### 3.1 Worker Dockerfile

```dockerfile
# worker/Dockerfile
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install simmer-sdk from local path (same as current setup)
COPY simmer-sdk/ /tmp/simmer-sdk/
RUN pip install --no-cache-dir /tmp/simmer-sdk/ && rm -rf /tmp/simmer-sdk/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/ worker/

# Cloud Run Jobs run the CMD once and exit.
CMD ["python", "-m", "worker.main"]
```

```
# worker/requirements.txt
anthropic[bedrock]
google-cloud-firestore
google-cloud-storage
firebase-admin
```

---

### 3.2 Worker entry point

```python
# worker/main.py
import os
import sys
from worker.runner import run_job

def main():
    job_id = os.environ.get("JOB_ID")
    workspace_id = os.environ.get("WORKSPACE_ID")

    if not job_id or not workspace_id:
        print("ERROR: JOB_ID and WORKSPACE_ID env vars required", file=sys.stderr)
        sys.exit(1)

    run_job(workspace_id=workspace_id, job_id=job_id)

if __name__ == "__main__":
    main()
```

```python
# worker/runner.py
from google.cloud import firestore
from datetime import datetime, timezone

db = firestore.Client()

def run_job(workspace_id: str, job_id: str):
    job_ref = db.collection(f"workspaces/{workspace_id}/jobs").document(job_id)
    job = job_ref.get().to_dict()

    if not job:
        raise ValueError(f"Job {job_id} not found")

    # Idempotency guard — Eventarc delivers at-least-once
    if job["status"] in ("running", "completed", "failed"):
        print(f"Job {job_id} already in status {job['status']}, skipping")
        return

    job_ref.update({
        "status": "running",
        "startedAt": datetime.now(timezone.utc),
    })

    try:
        job_type = job["type"]
        if job_type == "simmer_general":
            from worker.jobs.simmer_general import run_simmer_general
            run_simmer_general(db, workspace_id, job_id, job)
        elif job_type == "simmer_domain":
            from worker.jobs.simmer_domain import run_simmer_domain
            run_simmer_domain(db, workspace_id, job_id, job)
        elif job_type == "extract_batch":
            from worker.jobs.extract_batch import run_extract_batch
            run_extract_batch(db, workspace_id, job_id, job)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

        job_ref.update({
            "status": "completed",
            "completedAt": datetime.now(timezone.utc),
        })

    except Exception as e:
        job_ref.update({
            "status": "failed",
            "error": str(e),
            "completedAt": datetime.now(timezone.utc),
        })
        raise
```

---

### 3.3 Deploy the Cloud Run Job

```bash
PROJECT_ID="your-project-id"
REGION="us-central1"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/orrery/simmer-worker:latest"

docker build --platform linux/amd64 -t $IMAGE ./worker
docker push $IMAGE

gcloud run jobs create simmer-worker \
  --image=$IMAGE \
  --region=$REGION \
  --memory=2Gi \
  --cpu=2 \
  --task-timeout=3600s \
  --max-retries=0 \
  --project=$PROJECT_ID \
  --set-env-vars=FIRESTORE_PROJECT=$PROJECT_ID,EMBEDDING_SERVICE_URL=...

# Note: JOB_ID and WORKSPACE_ID are NOT set here.
# They are passed as overrides at execution time (see Cloud Function below).
```

`--max-retries=0` is important. Simmer jobs are expensive (Bedrock calls) and
idempotency is tricky — don't auto-retry on failure. Failed jobs get marked in
Firestore and can be manually re-queued.

---

### 3.4 Cloud Function trigger

This is a lightweight function (Node.js or Python) that watches the `jobs`
collection and fires Cloud Run Job executions. It does not run the pipeline
itself — it just dispatches.

```python
# functions/trigger_simmer/main.py
import os
import functions_framework
from google.cloud import run_v2

PROJECT_ID = os.environ["GCP_PROJECT"]
REGION = os.environ["CLOUD_RUN_REGION"]
JOB_NAME = "simmer-worker"

@functions_framework.cloud_event
def trigger_simmer_job(cloud_event):
    """Triggered when a job document is created in Firestore."""
    # Parse the Firestore document path from the event
    # Path format: projects/{proj}/databases/{db}/documents/workspaces/{wid}/jobs/{jid}
    resource = cloud_event.data.get("value", {})
    name = resource.get("name", "")

    # Extract workspace_id and job_id from path
    parts = name.split("/")
    # [..., "workspaces", workspace_id, "jobs", job_id]
    try:
        ws_idx = parts.index("workspaces")
        workspace_id = parts[ws_idx + 1]
        job_id = parts[ws_idx + 3]
    except (ValueError, IndexError):
        print(f"Could not parse path: {name}")
        return

    # Read job status from event data to avoid re-triggering running jobs
    fields = resource.get("fields", {})
    status = fields.get("status", {}).get("stringValue", "")
    job_type = fields.get("type", {}).get("stringValue", "")

    if status != "queued":
        return  # Only dispatch newly queued jobs

    if job_type not in ("simmer_general", "simmer_domain", "extract_batch"):
        return

    print(f"Dispatching job {job_id} (type={job_type}) for workspace {workspace_id}")

    # Trigger the Cloud Run Job with env var overrides
    client = run_v2.JobsClient()
    job_name = f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{JOB_NAME}"

    request = run_v2.RunJobRequest(
        name=job_name,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    env=[
                        run_v2.EnvVar(name="JOB_ID", value=job_id),
                        run_v2.EnvVar(name="WORKSPACE_ID", value=workspace_id),
                    ]
                )
            ]
        ),
    )

    # Fire-and-forget — the operation runs async, we don't wait
    operation = client.run_job(request=request)
    print(f"Started execution: {operation.metadata}")
```

**IAM requirements for the Cloud Function's service account:**
- `roles/run.invoker` on the Cloud Run Job
- `roles/datastore.user` on Firestore (to read the triggering document)

**Deploy the trigger:**
```bash
gcloud run deploy trigger-simmer \
  --source ./functions/trigger_simmer \
  --function trigger_simmer_job \
  --base-image python313 \
  --region us-central1 \
  --no-allow-unauthenticated \
  --set-env-vars GCP_PROJECT=$PROJECT_ID,CLOUD_RUN_REGION=us-central1

# Attach Firestore trigger via Eventarc
gcloud eventarc triggers create trigger-simmer-jobs \
  --location=us-central1 \
  --destination-run-service=trigger-simmer \
  --destination-run-region=us-central1 \
  --event-filters="type=google.cloud.firestore.document.v1.created" \
  --event-filters="database=(default)" \
  --event-filters-path-pattern="document=workspaces/*/jobs/*" \
  --service-account=PROJECT_NUMBER-compute@developer.gserviceaccount.com
```

> **Eventarc at-least-once:** The function may fire more than once for the
> same document creation. The `status != "queued"` check at the top is the
> primary guard. The `runner.py` status check (`if job["status"] in ("running",
> "completed", "failed"): return`) is the secondary guard inside the job
> itself. Both are needed.

---

### 3.5 Migrating worker from SQLite to Firestore

The existing worker jobs (`simmer_general.py`, `simmer_domain.py`,
`extract_batch.py`) use raw SQLite calls. Replace them with the repository
pattern that the orchestrator already uses.

**The orchestrator already has a working Firestore repository layer.** The
simplest migration path:

1. Import the same repository classes into the worker
2. Replace all `sqlite3` / `db.execute()` calls with repository method calls
3. The `on_iteration` callback that writes to `simmerIterations` already exists
   — verify it uses the Firestore repo, not SQLite

Files to migrate:
- `worker/src/jobs/simmer_general.py` — replace DB reads (get docs, load spec) and writes (store spec, golden set)
- `worker/src/jobs/simmer_domain.py` — same pattern
- `worker/src/jobs/extract_batch.py` — replace entity reads/writes, cooccurrence writes
- `worker/src/jobs/runner.py` — replace job status management (already replaced in `runner.py` above)

The worker also needs to call the embedding service for batch extraction
(embedding new entities after extraction). Use the same `embed_texts()` helper
from the orchestrator.

---

## Part 4: Multi-Tenancy

### Overview

Architecture: one Firebase project, one Firestore database, data isolated by
Firestore path and Security Rules. Users belong to an org. Each org has one or
more workspaces. Access is enforced via custom claims in the JWT.

```
organizations/{orgId}/
  members/{userId}/         role: admin|editor|viewer
  workspaces/{workspaceId}/
    documents/, entities/, domains/, jobs/, specs/ ...
```

Roll this out **after** embeddings + vector search + simmer are working.

---

### 4.1 Custom claims structure

```python
# The claims on every user's JWT token
{
    "orgId": "org_abc123",
    "role": "editor"       # admin | editor | viewer
}
```

Set via Admin SDK (Python, server-side only):

```python
# orchestrator/src/auth_admin.py
from firebase_admin import auth

def set_user_claims(uid: str, org_id: str, role: str):
    """Call this when a user is added to an org or their role changes."""
    auth.set_custom_user_claims(uid, {
        "orgId": org_id,
        "role": role,
    })

def get_user_claims(uid: str) -> dict:
    user = auth.get_user(uid)
    return user.custom_claims or {}
```

**Token refresh caveat:** After `set_custom_user_claims()`, the user's existing
token is stale for up to 1 hour. To force immediate refresh:
- Backend writes a sentinel doc to `users/{uid}/tokenRefresh/{timestamp}`
- Frontend watches this path with `onSnapshot`
- When it changes: `await user.getIdToken(true)` forces token refresh

This is the standard pattern documented by Firebase.

---

### 4.2 Firestore Security Rules

```javascript
// firestore.rules
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // Helper functions — evaluated per request, no extra reads
    function isSignedIn() {
      return request.auth != null;
    }

    function userOrg() {
      return request.auth.token.orgId;
    }

    function userRole() {
      return request.auth.token.role;
    }

    function isAdmin() {
      return isSignedIn() && userRole() == 'admin';
    }

    function isEditor() {
      return isSignedIn() && userRole() in ['admin', 'editor'];
    }

    function isViewer() {
      return isSignedIn() && userRole() in ['admin', 'editor', 'viewer'];
    }

    function belongsToOrg(orgId) {
      return isSignedIn() && userOrg() == orgId;
    }

    // Org-level documents
    match /organizations/{orgId} {
      allow read: if belongsToOrg(orgId) && isViewer();
      allow write: if belongsToOrg(orgId) && isAdmin();

      // Member management
      match /members/{userId} {
        allow read: if belongsToOrg(orgId) && isViewer();
        allow write: if belongsToOrg(orgId) && isAdmin();
      }

      // Workspace data — all collections under workspaces
      match /workspaces/{workspaceId} {
        allow read: if belongsToOrg(orgId) && isViewer();
        allow create, update: if belongsToOrg(orgId) && isEditor();
        allow delete: if belongsToOrg(orgId) && isAdmin();

        // All subcollections under a workspace follow the same role pattern
        match /{collection}/{docId} {
          allow read: if belongsToOrg(orgId) && isViewer();
          allow create, update: if belongsToOrg(orgId) && isEditor();
          allow delete: if belongsToOrg(orgId) && isAdmin();

          // Subcollections (e.g. jobs/{id}/iterations/{id})
          match /{subCollection}/{subDocId} {
            allow read: if belongsToOrg(orgId) && isViewer();
            allow write: if belongsToOrg(orgId) && isEditor();
          }
        }
      }
    }

    // User-specific metadata (token refresh signal)
    match /users/{userId} {
      allow read, write: if request.auth.uid == userId;
    }
  }
}
```

> **Admin SDK bypasses rules.** All backend services (orchestrator, worker,
> Cloud Functions) use the Admin SDK, which has full unrestricted access.
> Security rules only protect client SDK calls (frontend). This is correct
> and intentional — your backend is trusted.

---

### 4.3 Org creation flow (first sign-in)

```python
# orchestrator/src/routes/auth.py

@router.post("/auth/provision")
async def provision_user(user: AuthUser = Depends(get_current_user)):
    """
    Called by frontend after first sign-in.
    Creates org if none exists for this user, sets claims.
    """
    claims = get_user_claims(user.uid)

    if claims.get("orgId"):
        # Already provisioned — return existing org
        return {"orgId": claims["orgId"], "role": claims["role"]}

    # Create new org
    org_ref = db.collection("organizations").document()
    org_id = org_ref.id

    org_ref.set({
        "name": f"{user.email.split('@')[0]}'s Org",
        "createdAt": firestore.SERVER_TIMESTAMP,
        "createdBy": user.uid,
    })

    # Add user as admin
    org_ref.collection("members").document(user.uid).set({
        "role": "admin",
        "email": user.email,
        "joinedAt": firestore.SERVER_TIMESTAMP,
    })

    # Create default workspace
    ws_ref = org_ref.collection("workspaces").document()
    ws_ref.set({
        "name": "Default",
        "createdBy": user.uid,
        "createdAt": firestore.SERVER_TIMESTAMP,
    })

    # Set custom claims
    set_user_claims(user.uid, org_id, "admin")

    # Signal frontend to refresh token
    db.collection("users").document(user.uid).set({
        "tokenRefreshAt": firestore.SERVER_TIMESTAMP
    }, merge=True)

    return {"orgId": org_id, "workspaceId": ws_ref.id, "role": "admin"}
```

---

### 4.4 Invite flow

```python
# orchestrator/src/routes/invites.py

@router.post("/invites")
async def create_invite(
    email: str,
    role: str,
    user: AuthUser = Depends(require_role("admin")),
):
    """Admin invites a new user by email."""
    invite_ref = db.collection("invites").document()
    invite_ref.set({
        "email": email.lower(),
        "role": role,
        "orgId": user.org_id,
        "createdBy": user.uid,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "status": "pending",
    })
    return {"inviteId": invite_ref.id}


@router.post("/auth/accept-invite")
async def accept_invite(user: AuthUser = Depends(get_current_user)):
    """
    Called after sign-in if user has no claims yet.
    Checks for pending invite matching their email.
    """
    invites = (
        db.collection("invites")
        .where("email", "==", user.email.lower())
        .where("status", "==", "pending")
        .limit(1)
        .get()
    )

    if not invites:
        return {"invited": False}

    invite = invites[0].to_dict()
    org_id = invite["orgId"]
    role = invite["role"]

    # Add to org
    org_ref = db.collection("organizations").document(org_id)
    org_ref.collection("members").document(user.uid).set({
        "role": role,
        "email": user.email,
        "joinedAt": firestore.SERVER_TIMESTAMP,
    })

    # Set claims
    set_user_claims(user.uid, org_id, role)

    # Mark invite consumed
    invites[0].reference.update({"status": "accepted"})

    # Signal token refresh
    db.collection("users").document(user.uid).set({
        "tokenRefreshAt": firestore.SERVER_TIMESTAMP
    }, merge=True)

    return {"orgId": org_id, "role": role, "invited": True}
```

---

### 4.5 Frontend token refresh watcher

```javascript
// frontend/src/lib/auth.js
import { onSnapshot, doc } from 'firebase/firestore';
import { getAuth } from 'firebase/auth';

export function watchTokenRefresh(userId, db) {
  const auth = getAuth();
  const userDocRef = doc(db, 'users', userId);

  return onSnapshot(userDocRef, async (snap) => {
    if (snap.exists()) {
      // Backend signaled a claims change — force token refresh
      await auth.currentUser?.getIdToken(true);
      console.log('Token refreshed after claims update');
    }
  });
}

// Call this in your auth state change handler
onAuthStateChanged(auth, (user) => {
  if (user) {
    watchTokenRefresh(user.uid, db);
    // Also call /auth/provision or /auth/accept-invite
  }
});
```

---

### 4.6 Workspace selector

```javascript
// frontend/src/components/WorkspaceSelector.jsx
// Reads user's available workspaces from Firestore and lets them switch.
// URL structure: /w/{workspaceId}/viz, /w/{workspaceId}/entities etc.

import { collection, query, onSnapshot } from 'firebase/firestore';

function WorkspaceSelector({ orgId, currentWorkspaceId, onSwitch }) {
  const [workspaces, setWorkspaces] = useState([]);

  useEffect(() => {
    const q = query(
      collection(db, `organizations/${orgId}/workspaces`)
    );
    return onSnapshot(q, (snap) => {
      setWorkspaces(snap.docs.map(d => ({ id: d.id, ...d.data() })));
    });
  }, [orgId]);

  return (
    <select
      value={currentWorkspaceId}
      onChange={(e) => onSwitch(e.target.value)}
    >
      {workspaces.map(ws => (
        <option key={ws.id} value={ws.id}>{ws.name}</option>
      ))}
    </select>
  );
}
```

---

## Part 5: Implementation Order

Do these in sequence. Each unlocks the next.

### Step 1 — Embedding service (1-2 days)
1. Write `embedding_service/Dockerfile` and `main.py` per Part 1
2. Build with `--platform linux/amd64` (required if dev on Apple Silicon)
3. Push to Artifact Registry
4. Deploy to Cloud Run (min-instances=0 to start)
5. Write `orchestrator/src/services/embedding.py` helper
6. Add `EMBEDDING_SERVICE_URL` env var to orchestrator Cloud Run deployment
7. Add `/internal/warm` endpoint to orchestrator that calls embed service
8. Test: POST to `/embed` directly, confirm 384-dim vectors returned

### Step 2 — Firestore vector indexes (0.5 days)
1. Run the two `gcloud firestore indexes composite create` commands (entities + chunks)
2. Wait for indexes to build (can take 5-30 min, check console)
3. Commit the commands to `scripts/create_indexes.sh`

### Step 3 — Wire embedding into ingest (0.5 days)
1. In the ingest pipeline, after entities are stored in Firestore, call
   `embed_texts([entity.canonicalName for entity in new_entities])`
2. Write resulting vectors back with `entity_ref.update({"embedding": Vector(vec)})`
3. Same for chunks: embed `chunk.text`, write to chunk doc
4. Test: ingest a document, confirm embedding field appears on entity docs

### Step 4 — Vector search route (0.5 days)
1. Update `search/retrieval.py` to use `find_nearest()` per Part 2.4
2. Wire into search pipeline (query → embed → find_nearest → boost → fuse)
3. Keep keyword search as parallel fallback — merge results during transition
4. Test: search for something, confirm semantic results better than keyword

### Step 5 — Backfill (0.5 days)
1. Write `scripts/backfill_embeddings.py` — page through existing entities/chunks
2. Run locally or as Cloud Run Job
3. Confirm all entities have `embedding` field
4. Disable keyword search fallback

### Step 6 — Simmer worker (2-3 days)
1. Write worker `Dockerfile`, `main.py`, `runner.py` per Part 3
2. Migrate worker job files from SQLite to Firestore repositories
3. Deploy Cloud Run Job
4. Write and deploy trigger Cloud Function
5. Create Eventarc trigger
6. Test: create a job doc manually in Firestore, confirm worker picks it up

### Step 7 — Multi-tenancy (3-4 days, after above is stable)
1. Write security rules per Part 4.2, deploy, test in Rules Playground
2. Implement `/auth/provision` endpoint
3. Implement invite flow endpoints
4. Add token refresh watcher to frontend
5. Build workspace selector UI
6. URL routing per workspace (`/w/{workspaceId}/...`)
7. Test: two users, two orgs, confirm cross-org data isolation

---

## Gotchas Reference

| Issue | What to do |
|---|---|
| `--platform linux/amd64` required when building on Mac M-series | Always include this flag |
| Firestore `find_nearest()` returns distance differently per SDK version | Check installed `google-cloud-firestore` version docs for exact attribute name |
| Eventarc fires at-least-once | Guard with status check in both the Cloud Function AND the worker |
| Custom claims take up to 1 hour to propagate without forced refresh | Implement the `users/{uid}` sentinel doc + `getIdToken(true)` pattern |
| Vector index build takes time | Create indexes before deploying the search route change |
| Embedding model must be same for all stored vectors | Never change models without re-embedding everything and recreating indexes |
| Cloud Run Job `--max-retries=0` | Simmer jobs should not auto-retry — Bedrock calls are expensive |
| Worker needs embedding service URL | Pass as env var in Cloud Run Job definition |
| Admin SDK bypasses Security Rules | Rules only protect the frontend client SDK — this is correct |
| Composite index needed for `where()` + `find_nearest()` | If pre-filtering entities by workspace before vector search, need a composite index with both fields |
