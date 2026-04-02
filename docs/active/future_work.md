# Future Work

Tracked improvements and architecture changes. Items move from active
to done as they're completed.

---

## DONE (2026-04-02)

### Simmer Worker: Split into Phase-Based Jobs
Split `simmer_general` into `simmer_golden_set` + `simmer_extraction_spec`.
Each runs in its own Cloud Run Job with fresh resources. Golden set saves
artifact to Firestore between phases. Parent `simmer_general` job tracks
both phases — iterations written to parent ID, UI shows one unified entry.

### Cloud Pipeline: Post-Extraction Steps
Shared `post_process.py` runs after batch extraction:
embed entities (Vertex AI, batched) → cooccurrences → UMAP layout → graph cache.
Called by `extract_batch.py` and also available as standalone `post_process` job type.

### Graph Cache
Precomputed graph JSON stored in `workspaces/{id}/cache/graph`. The `/graph`
endpoint reads this directly — eliminates N+1 Firestore queries that caused
30s timeouts. Cache uses the exact format the viz expects (`domain_positions`,
`trade_routes`, `domain_specs`, etc.).

### Firestore Vector Search
Search endpoint uses Vertex AI `find_nearest()` on stored entity embeddings.
Falls back to FAISS on SQLite. Full pipeline: expansion (optional) → vector
search + exact match → entity boost → fusion → chunk context.

### Auth on All Viz Iframes
All viz HTML files (index, star, sector, system) read auth token + workspace
ID from URL params. All orrery pages pass them through. Search uses
`expand=false` for UI, `expand=true` for agents/MCP.

### Job Chain Automation
Cloud Function trigger handles all job types: `simmer_general`,
`simmer_golden_set`, `simmer_extraction_spec`, `simmer_domain`,
`extract_batch`, `post_process`. Full chain fires automatically.

### Bedrock Model IDs
Sonnet 4.6 = `us.anthropic.claude-sonnet-4-6` (no -v1:0 suffix).
Verified against `aws bedrock list-inference-profiles`. 6M TPM quota.

### Worker CLI Fix
Installed system Claude CLI (v2.1.90) via npm in worker Dockerfile.
Fixes `Control request timeout: initialize` from bundled v2.1.88.

---

## ACTIVE — Short Term

### Fix Remaining Bare Fetch Calls
**Status:** DONE — all bare `fetch('/api/...')` calls now include auth
headers and workspace ID. No remaining unauthed API calls in frontend.

### Post-Ingest Processing Trigger
**Problem:** When docs are uploaded and extracted inline (spec already
exists), the post-processing steps (embed, cooccurrences, UMAP, graph
cache) don't run. Only batch extraction triggers them.

**Fix:** After inline ingest extraction, queue a `post_process` job.
The Cloud Function triggers the worker to run the shared pipeline.
The `post_process` job type and Cloud Function trigger already exist —
just need the orchestrator's ingest route to create the job.

**Priority:** HIGH — without this, uploading new docs to an existing
noosphere doesn't update the orrery.

### Viz Iframe Auth: Longer Term Fix
**Problem:** Auth tokens passed via URL params (visible in logs, browser
history). Works but not ideal.

**Fix options:**
1. PostMessage token exchange between parent page and iframe
2. Server-side proxy that injects auth headers (Next.js middleware)

**Priority:** LOW — current approach works fine for internal tool.

### Domain-Specific Simmering
**Problem:** Only general spec simmering works end-to-end. Domain-specific
simmering (`simmer_domain`) exists in code but hasn't been tested with
the new split pipeline.

**Fix:** Extend the parent/child pattern to domain-specific simmers.
Test with a domain from the Magos Lex noosphere.

**Priority:** MEDIUM — enriches the orrery (individual domains glow when
they have their own spec).

---

## ACTIVE — Medium Term

### Adapter Formalization (Local vs Cloud)
Implicit adapters (SQLite/Firestore, DEV_USER/Firebase, sentence-transformers/
Vertex AI) work but are scattered env-var checks. Formalize into container/DI
pattern. ~70% done, ~2-3 days. See `local_vs_cloud_architecture.md`.

**Priority:** LOW — do when external contributors need local instances.

### Simmer-SDK Issues
Filed on github.com/2389-research/simmer-sdk:
- **#1** Regression detection should use primary criterion, not just composite
- **#2** Bundled CLI broken on Cloud Run (workaround: system CLI)
- **#3** Plateau detection should stop early after N identical composites

### Simmer-SDK Resumability
If a simmer phase is interrupted, it restarts from scratch. Should check
Firestore for existing iterations and resume. Prevents wasted compute.

**Priority:** MEDIUM — phase splitting reduces the impact but doesn't
eliminate it.

### Frontend: Noop Auth for Local Mode
Add `NEXT_PUBLIC_AUTH_MODE=noop|firebase` for `docker compose up` experience.
NoopAuthProvider returns fake admin user.

**Priority:** LOW

---

## ACTIVE — Onboarding & Polish

### Onboarding Tutorial Overlay
5-step walkthrough using Magos mascot images (in `public/mascot/`):
1. Orrery (galxy.png) — the wow
2. Search (pointing.png) — the power move
3. Entities (reading.png) — the detail layer
4. Pipeline (thinking.png) — the engine
5. The Unlock (happy.png) — create your own

Depends on Magos Noosphere being set up as read-only demo workspace.
Demo mode infrastructure exists (`DemoModeContext`, `useDemoMode()`,
`NEXT_PUBLIC_MAGOS_WORKSPACE_ID`). Content is loaded (22 docs, 779
entities, 33 domains).

**Priority:** MEDIUM

### Merge firebase-migration Branch
80+ commits ahead of main. Rebased on orrery-relay PR.
Pipeline works end-to-end: upload → classify → simmer → extract →
embed → orrery renders.

**Remaining before merge:**
- Run full pipeline on a clean workspace to verify automation
- Test the new parent/child simmer job chain end-to-end
- Verify `post_process` job fires correctly from Cloud Function
- Update tests (some may need adjusting for new job types)

**Priority:** HIGH
