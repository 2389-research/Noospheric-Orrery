# Future Work

Tracked improvements and architecture changes. Not urgent — captured here
so they don't get lost between sessions.

---

## Simmer Worker: Split into Phase-Based Jobs

**Problem:** The simmer worker runs Golden Set + Extraction Spec sequentially
in a single Cloud Run Job execution. With investigation-first judges (Claude
CLI with Read/Grep/Glob tools) and board deliberation, each phase can take
45-60+ minutes. A 1-hour timeout kills the job mid-extraction-spec even
though golden set completed fine. Currently bumped to 2 hours but that's a
bandaid.

**Fix:** Split into two separate Cloud Run Job executions:

```
Job 1: simmer_golden_set
  - Runs golden set refinement (~5 iterations)
  - Saves best golden set artifact to Firestore specs collection
  - Marks phase complete
  - Triggers Job 2

Job 2: simmer_extraction_spec
  - Reads golden set from Firestore
  - Runs extraction spec refinement (~5 iterations)  
  - Saves best extraction spec
  - Triggers batch extraction
```

**Benefits:**
- Each phase gets its own full timeout window
- If extraction spec fails, golden set output is preserved
- Can retry just the failed phase
- Progress is visible between phases (not just at the end)
- Could parallelize domain-specific spec runs after general spec

**Scope:** simmer-sdk worker code + Cloud Function trigger logic. The
simmer-sdk `refine()` API already returns after each call — the sequential
chaining is in `worker-cloud/worker/jobs/simmer_general.py`.

**Priority:** Medium — blocks reliable pipeline completion. Current workaround
is 2-hour timeout.

---

## Adapter Formalization (Local vs Cloud)

**Problem:** The codebase has implicit adapters (SQLite vs Firestore, DEV_USER
vs Firebase JWT, sentence-transformers vs Vertex AI) but they're scattered
env-var checks and try/except blocks, not formal interfaces.

**Fix:** Formalize into a container/DI pattern with explicit adapter
interfaces. See memory note `local_vs_cloud_architecture.md` for full
analysis. ~70% done, ~2-3 days to formalize.

**Priority:** Low — current approach works fine. Do this when external
contributors need to run local instances or when adding new adapters
(Postgres, S3, etc).

---

## Simmer-SDK Resumability

**Problem:** If a simmer run is interrupted (timeout, crash), it restarts
from scratch. Previous iterations are in Firestore but simmer-sdk doesn't
read them back.

**Fix:** On startup, check Firestore for existing iterations for this job.
If found, reconstruct the trajectory and resume from the last iteration
instead of starting over. The simmer-sdk `refine()` function would need a
`resume_from` parameter or auto-detect existing state.

**Priority:** Medium — directly related to the timeout issue. Even with
phase splitting, resumability prevents wasted compute.

---

## Frontend: Noop Auth for Local Mode

**Problem:** The frontend always tries Firebase Auth. Local users without
Firebase config see "Firebase not configured" errors.

**Fix:** Add `NEXT_PUBLIC_AUTH_MODE=noop|firebase` env var. When `noop`,
use a `NoopAuthProvider` that returns a fake admin user. All auth-aware
components work unchanged.

**Priority:** Low — needed for "anyone can docker compose up" experience.

---

## Onboarding Tutorial Overlay

**Problem:** New users land in the app with no guidance. The Magos Noosphere
content exists but there's no tutorial walkthrough.

**Fix:** Build the 5-step tutorial overlay from `tutorial_oboarding_fun.md`:
1. Orrery (the wow) — mascot with `galxy.png`
2. Search (the power move) — mascot with `pointing.png`
3. Entities (the detail layer) — mascot with `reading.png`
4. Pipeline (the engine) — mascot with `thinking.png`
5. The Unlock (create your own) — mascot with `happy.png`

Components: `<TutorialOverlay>`, `<MascotPanel>`, `<NamingScreen>`

**Priority:** Medium — depends on Magos Noosphere content being loaded and
the demo read-only mode working.

---

## Merge firebase-migration Branch

**Status:** 50+ commits ahead of main. Rebased on top of orrery-relay PR.
All 82 tests passing.

**Blockers:**
- Verify pipeline completes end-to-end (simmer → extraction → entities)
- Test with real user flow (sign in → provision → upload → pipeline → orrery)
- Reconcile Dockerfile (our Python 3.13 vs relay's Python 3.11 — resolved to 3.13)

**Priority:** High — everything else builds on this.
