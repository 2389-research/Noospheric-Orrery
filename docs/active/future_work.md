# Future Work

Tracked improvements and architecture changes.

---

## DONE (2026-04-11)

- **Local-first simplification** — removed all Firebase/Firestore/Google Cloud dependencies. SQLite is the only backend. No auth required. Archive tags `firebase-archive-v1` and `firebase-archive-v1-restore` preserve the cloud work.
- **Frontend Firebase removal** — replaced Firebase Auth SDK with local noop auth. Removed `firebase` npm dependency. All hooks use API instead of Firestore listeners.
- **Multi-workspace preserved** — SQLite workspaces via JSON registry + separate .db files. Same UI, no cloud dependency.

## DONE (2026-04-08 — 2026-04-11)

- **General extraction specs** — text + image docs extract entities on upload without simmering first. Specs as editable markdown in `orchestrator/specs/`.
- **Image pipeline** — upload, classify, extract, search, serve images (local filesystem).
- **Universal UMAP model** — 100 training domains, model stored locally, `transform()` for new domains.
- **CPU-only torch** — pytorch-cpu index in pyproject.toml. ~5GB savings per image.

## DONE (2026-04-01 — 2026-04-07)

- **Multi-tenancy backend** — provision, invites, workspace CRUD, role hierarchy
- **Frontend route restructure** — all routes under `/n/[noosphereId]/...`, noosphere switcher, settings pages
- **Simmer split pipeline** — golden_set + extraction_spec as separate jobs
- **Post-extraction pipeline** — embed → cooccurrences → UMAP → graph cache
- **Ollama backend** — `ANTHROPIC_BACKEND=ollama` with gemma4 models for fully local pipeline
- **Structured output** — all LLM calls use `relay.complete_structured()`

---

## REMAINING — High Priority

### Domain Normalization
Duplicate domains from format inconsistency (underscores vs hyphens). Apply the same embedding similarity + merge map pattern used for entity normalization.

### Re-simmer Button in UI
No way to re-trigger a simmer run from the UI once one has completed.

### Image Pipeline — Local Storage Adaptation
Image upload/extract/search pipeline is functional (see DONE 2026-04-08). Remaining work: verify local filesystem storage paths are consistent across Docker and native dev, and add tests for image ingest flow.

---

## REMAINING — Medium Priority

### GHCR Multi-Arch Images
Release workflow builds x86 only. Mac users get QEMU emulation (5-10x slower). Need `--platform linux/amd64,linux/arm64` in the build matrix.

### Onboarding Tutorial Overlay
Magos content loaded. Demo mode infrastructure built. Needs the 5-step tutorial UI.

### Domain Taxonomy Simmering
Currently simmers at leaf domain level only. Could simmer at parent levels.

### Post-Process Visibility in UI
The post_process job runs silently. Pipeline page could show an indicator.

---

## KNOWN ISSUES

### UMAP transform() on ARM Docker
`transform()` doesn't work on ARM Docker (Mac). `NUMBA_DISABLE_JIT=1` breaks it, without it SIGILL. `fit_transform()` works. Local SQLite mode uses `full_fit` which works.

### UMAP Layout: Embedding Model Change
If embedding model changes dimensions, stored UMAP model can't transform — dimension mismatch. Fix: detect and trigger re-fit.

---

## REMAINING — Low Priority

### Simmer-SDK Resumability
Resume interrupted simmer phases from existing iterations instead of restarting.

### Simmer-SDK Model IDs
The simmer-sdk's `client.py` still maps `claude-sonnet-4-6` to the old Sonnet 4.5 Bedrock ID. Should use `us.anthropic.claude-sonnet-4-6` like orrery-relay does. This is in the simmer-sdk repo, not ours.
