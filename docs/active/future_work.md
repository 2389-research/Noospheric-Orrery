# Future Work

Tracked improvements and architecture changes.

---

## DONE (2026-04-08 — 2026-04-11)

- **General extraction specs** — text + image docs extract entities on upload without simmering first. Specs as editable markdown in `orchestrator/specs/`.
- **Image pipeline** — upload, classify, extract, search, serve images. Firebase Storage in cloud mode, local filesystem in SQLite mode.
- **Universal UMAP model** — 100 training domains, model on Cloud Run, `transform()` for new domains. Scripts for corpus generation, fitting, seeding.
- **CPU-only torch** — pytorch-cpu index in both orchestrator + worker pyproject.toml. ~5GB savings per image.
- **Frontend: image upload** — separate text/image upload zones, image search toggle, ImagePane with clickable domain tags.
- **Frontend: auth fixes** — iframe token refresh, star view URL param preservation, noop mode for local dev.
- **Firestore fixes** — `_safe_doc_id` for entity names with `/`, image search via Vertex AI embeddings, `update_content`/`update_text` repository methods.
- **Firebase dev stack** — emulator with Java 21, 0.0.0.0 binding, noop auth mode.
- **Docker improvements** — `--no-install-project` pattern (Harper PR #15), specs directory in Dockerfile.

## DONE (2026-04-01 — 2026-04-07)

- **Multi-tenancy backend** — provision, invites, workspace CRUD, role hierarchy, Firestore security rules
- **Frontend route restructure** — all routes under `/n/[noosphereId]/...`, noosphere switcher, settings pages
- **Simmer split pipeline** — golden_set + extraction_spec as separate Cloud Run Jobs
- **Post-extraction pipeline** — embed → cooccurrences → UMAP → graph cache
- **Evaluator** — empirical evaluator for simmer, golden set with real entities
- **Ollama backend** — `ANTHROPIC_BACKEND=ollama` with gemma4 models for fully local pipeline
- **Image pipeline (Docker)** — single-stage image simmer, batch extraction, SigLIP embeddings
- **Structured output** — all LLM calls use `relay.complete_structured()`

---

## REMAINING — High Priority

### PR #17: Restore Image Pipeline on Main
Code was lost during a revert cycle. PR #17 re-applies it. Needs merge + v0.2.1 tag + GHCR rebuild.

### Domain Normalization
Duplicate domains from format inconsistency (underscores vs hyphens). Apply the same embedding similarity + merge map pattern used for entity normalization. This is the right way to handle `ai_development` vs `ai-development` — not format enforcement at the classifier.

### Local-First Focus
Harper feedback: prioritize the `docker compose up` experience. The local pipeline (SQLite + Ollama + sentence-transformers) is the core product. Cloud features (Firestore, Firebase Auth, Vertex AI) preserved on a branch or behind flags.

### Cloud Worker Redeploy
The `simmer-worker` Cloud Run Job needs the updated post-process code with UMAP `transform()` using the universal model. Currently deployed with old code.

---

## REMAINING — Medium Priority

### GHCR Multi-Arch Images
Release workflow builds x86 only. Mac users get QEMU emulation (5-10x slower). Need `--platform linux/amd64,linux/arm64` in the build matrix.

### Re-simmer Button in UI
No way to re-trigger a simmer run from the UI once one has completed.

### Onboarding Tutorial Overlay
Magos content loaded. Demo mode infrastructure built. Needs the 5-step tutorial UI.

### Domain Taxonomy Simmering
Currently simmers at leaf domain level only. Could simmer at parent levels.

### Post-Process Visibility in UI
The `post_process` job runs silently. Pipeline page could show an indicator.

---

## KNOWN ISSUES

### UMAP transform() on ARM Docker
`transform()` doesn't work on ARM Docker (Mac). `NUMBA_DISABLE_JIT=1` breaks it, without it SIGILL. `fit_transform()` works. The universal UMAP model requires Cloud Run (x86) for `transform()`. Local SQLite mode uses `full_fit` which works.

### UMAP Layout: Embedding Model Change
If embedding backend changes (sentence-transformers 384-dim vs Vertex AI 768-dim), stored UMAP model can't transform — dimension mismatch. Fix: detect and trigger re-fit.

### Graph Cache Staleness on Firestore
Post-process worker builds graph cache. If positions or domains change outside the worker (manual edits, migrations), the cache serves stale data until next post-process run.

---

## REMAINING — Low Priority

### Viz Iframe Auth Improvement
Tokens in URL params works but not ideal. Better: postMessage exchange.

### Adapter Formalization (Local vs Cloud)
Implicit adapters work. Formalize into container/DI pattern when needed. ~70% done.

### Simmer-SDK Resumability
Resume interrupted simmer phases from existing iterations instead of restarting.

### SigLIP Embeddings in Batch Extraction
Image batch extraction uses sentence-transformers fallback. Should compute SigLIP embeddings for native cross-modal search.
