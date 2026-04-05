# Future Work

Tracked improvements and architecture changes.

---

## DONE (2026-04-01 — 2026-04-02)

- **Multi-tenancy backend** — provision, invites, workspace CRUD, role hierarchy, Firestore security rules
- **Frontend route restructure** — all routes under `/n/[noosphereId]/...`, noosphere switcher, settings pages
- **Simmer split pipeline** — golden_set + extraction_spec as separate Cloud Run Jobs with parent tracking
- **Domain-specific simmering** — same split pattern, scoped to domain docs, extends general spec
- **Post-extraction pipeline** — shared `post_process.py`: embed → cooccurrences → UMAP → graph cache
- **Post-ingest trigger** — auto-queues `post_process` after inline extraction on Firestore
- **Graph cache** — precomputed JSON in Firestore, eliminates N+1 queries
- **Firestore vector search** — Vertex AI `find_nearest()` replaces FAISS for cloud mode
- **Structured output** — all LLM calls use `relay.complete_structured()` with tool use (no more JSONL parsing)
- **Auth on all viz iframes** — token + workspace ID passed to all iframe API calls
- **Job chain automation** — Cloud Function triggers all job types automatically
- **Bedrock model IDs** — Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`), 6M TPM
- **Worker CLI fix** — system Claude CLI v2.1.90 via npm
- **Simmer-SDK score fix** — consensus scores stamped at top of board raw_text (#4)
- **Image size** — orchestrator 333MB (was 5.7GB), removed CUDA/torch/sentence-transformers from cloud deps
- **Score backfill** — corrected composites from criterion details where simmer-sdk reported wrong values

---

## REMAINING — High Priority

### Merge firebase-migration Branch
90+ commits ahead of main. Pipeline works end-to-end. All features tested live.

**Before merge:**
- Run orchestrator tests (`pytest tests/` — may need adjustments for new job types)
- Verify worker tests still pass
- Clean up any debugging artifacts
- PR review

### Re-simmer Button in UI
Currently no way to re-trigger a simmer run from the UI once one has completed.
Need a button on domain rows (pipeline page) and a re-trigger for general spec.

### Simmer-SDK Model IDs
The simmer-sdk's `client.py` still maps `claude-sonnet-4-6` to the old Sonnet 4.5
Bedrock ID. Should use `us.anthropic.claude-sonnet-4-6` like orrery-relay does.
This is in the simmer-sdk repo, not ours.

---

## REMAINING — Medium Priority

### Onboarding Tutorial Overlay
Magos content loaded (23 docs, 803 entities, 33 domains). Mascots ready.
Demo mode infrastructure built. Just needs the 5-step tutorial UI.

### Magos Demo Workspace Setup
Set `NEXT_PUBLIC_MAGOS_WORKSPACE_ID` in apphosting.yaml. Mark workspace
as `isDemo: true`. Security rules: all users get viewer access.

### Domain Taxonomy Simmering
Currently simmers at the leaf domain level only. Could simmer at parent
levels (e.g., `literature/science_fiction` covering all sci-fi docs).

### Post-Process Visibility in UI
The `post_process` job runs silently. Pipeline page could show a
"Updating orrery..." indicator when it's running.

---

## KNOWN ISSUES

### UMAP Layout: Embedding Model Change
If the embedding backend changes (e.g., switching from sentence-transformers
384-dim to Vertex AI 768-dim), the stored UMAP model can't transform new
domains because the feature dimensions don't match. Fix: detect dimension
mismatch and trigger a full re-fit. Current workaround: delete
`domain_layout` table / `domainLayout` collection to force re-fit.

### UMAP Layout: Circular Fallback Has No Model
When embeddings aren't available (Docker ARM without NUMBA_DISABLE_JIT,
or no embedding backend), the layout falls back to circular positioning.
This doesn't store a UMAP model, so `transform_new_domain()` can't
incrementally place new domains — they get random jitter positions until
a full re-fit happens.

---

## REMAINING — Low Priority

### Viz Iframe Auth Improvement
Tokens in URL params works but not ideal. Better: postMessage exchange
or server-side proxy injecting headers.

### Adapter Formalization (Local vs Cloud)
Implicit adapters work. Formalize into container/DI pattern when
external contributors need local instances. ~70% done.

### Frontend Noop Auth
`NEXT_PUBLIC_AUTH_MODE=noop|firebase` for `docker compose up` experience.

### Simmer-SDK Resumability
Resume interrupted simmer phases from existing iterations instead of
restarting. Phase splitting reduces impact but doesn't eliminate.
