# Domain Charter — Implementation Tracker

**Plan:** `docs/superpowers/plans/2026-08-20-domain-charter.md`
**Spec:** `docs/superpowers/specs/2026-08-20-domain-charter-design.md`
**Branch:** _not yet created_ — currently on `feature/onboarding-tutorial` (unrelated)

Update the status column as tasks land. Keep this file honest: a task is Done only when its
tests pass and it is committed.

---

## Progress

**0 / 7 tasks complete.** Nothing built yet.

```
Task 1  specs.source column          [ ] not started
Task 2  resolve_extraction_plan      [ ] not started
Task 3  wire into ingest             [ ] not started
Task 4  dry_run on POST /ingest      [ ] not started
Task 5  POST/GET /charter            [ ] not started
Task 6  simmer authored-seed mode    [ ] not started
Task 7  design-my-domain skill       [ ] not started
```

---

## What already exists (reused, not built)

Most of this feature is wiring into machinery that is already here. Worth knowing before
estimating — the new code is small because the slots exist.

| Mechanism | Where | Used for |
|---|---|---|
| Domain spec cascade (ancestor walk, dedup) | `orchestrator/src/routes/ingest.py:141-182` | moved into `resolve_extraction_plan`, logic unchanged |
| `domain_merge_map` table + lookup | `db.py:47`, `domain_normalizer.py:11`, `sqlite_store.py:276` | charter aliases — checked FIRST, before anything else |
| `specs` table + repository | `db.py:195`, `sqlite_store.py:651` | authored specs are ordinary rows |
| Existing-taxonomy block in the classifier prompt | `classifier.py:48` | a charter's domain row appears here from document 1 — no classifier change needed |
| Auto-simmer guard `spec_version IS NULL` | `ingest.py:189` | setting `spec_version` disables auto-simmer for free |
| `POST /simmer/{domain_path}` | `routes/simmer.py` | on-demand refinement of an authored spec |
| `extract_batch` re-extraction | `worker/src/jobs/extract_batch.py`, queued at `simmer_domain.py:188` | documents re-extracted after refinement, already automatic |
| Migration pattern (`ALTER TABLE ... IF NOT IN cols`) | `db.py:308-311` | the `source` column follows it exactly |
| Test fixtures (`test_store`, `test_client`, file-backed tmp DB) | `orchestrator/tests/conftest.py` | all new route tests |

---

## What must be built

| # | Task | Deliverable | Files | Status |
|---|---|---|---|---|
| 1 | `specs.source` column | the authored/simmered contract flag | `orchestrator/src/db.py`, `worker/src/db.py`, `interfaces.py`, `sqlite_store.py` | ☐ Not started |
| 2 | `resolve_extraction_plan` | pure decision function `(run_general, specs)` | `orchestrator/src/pipeline/extraction_plan.py` (new) | ☐ Not started |
| 3 | Wire into ingest | general pass becomes conditional | `orchestrator/src/routes/ingest.py:108-182` | ☐ Not started |
| 4 | `dry_run` | classify + extract, persist nothing | `orchestrator/src/models.py`, `routes/ingest.py` | ☐ Not started |
| 5 | `POST/GET /charter` | the one write endpoint | `orchestrator/src/routes/charter.py` (new), `main.py` | ☐ Not started |
| 6 | Authored-seed simmer | refinement keeps the authored contract | `worker/src/jobs/simmer_domain.py` | ☐ Not started |
| 7 | `design-my-domain` skill | the guided conversation | `.claude/skills/design-my-domain/SKILL.md` (new) | ☐ Not started |

### New test files

| File | Tests | Status |
|---|---|---|
| `orchestrator/tests/test_spec_source.py` | 4 | ☐ |
| `orchestrator/tests/test_extraction_plan.py` | 8 | ☐ |
| `orchestrator/tests/test_ingest_authored_spec.py` | 3 | ☐ |
| `orchestrator/tests/test_ingest_dry_run.py` | 3 | ☐ |
| `orchestrator/tests/test_charter_route.py` | 10 | ☐ |
| `worker/tests/test_simmer_authored_seed.py` | 4 | ☐ |

**32 new tests total.**

---

## Spec coverage

Every section of the design doc maps to a task. Nothing in the spec is unclaimed.

| Design section | Task | Status |
|---|---|---|
| The authored/simmered contract split | 1 | ☐ |
| §1 The extraction rule | 2, 3 | ☐ |
| §2 Pipeline change | 3 | ☐ |
| §3 Schema | 1 | ☐ |
| §4 Endpoints — `dry_run` | 4 | ☐ |
| §4 Endpoints — `POST /charter` | 5 | ☐ |
| §5 No taxonomy overlay | — | ✅ deliberately nothing to build |
| §6 Simmer seeding | 6 | ☐ |
| §7 The skill | 7 | ☐ |
| §8 Worth-it analysis | 7 | ☐ |

---

## Dependency order

```
Task 1 (specs.source)
   ├─→ Task 2 (resolve_extraction_plan) ─→ Task 3 (wire ingest) ─→ Task 4 (dry_run)
   ├─→ Task 5 (POST /charter)
   └─→ Task 6 (simmer authored seed)

Task 7 (skill) needs Tasks 4 and 5 shipped to be usable
```

- **Task 1 blocks everything.** Do it first.
- Tasks 2→3→4 are a strict chain.
- Tasks 5 and 6 are independent of that chain once Task 1 lands — parallelisable.
- Task 6 is genuinely last in value order: it is unreachable until a charter exists *and*
  documents have been ingested against it.

**Shippable midpoints:** after Task 3 the feature is inert but complete server-side (behaviour
unchanged with no charter). After Task 5 the feature works end-to-end via curl. Task 7 makes it
usable by a non-engineer.

---

## Risk register

| Risk | Where | Mitigation |
|---|---|---|
| **Refined spec stored as `simmered`** → general pass silently switches back on and the expert's exclusions stop working, after they were working | Task 6, Step 7 | explicit `spec_source` inheritance + the contract test in `test_simmer_authored_seed.py` |
| **Suppressing general for a *simmered* spec** → every base entity type silently vanishes | Task 2 | `run_general` tests `source == "authored"` only; `test_simmered_spec_still_runs_general` guards it |
| **Aliases stored unnormalised** → they never match, silently | Task 5, Step 4 | `.lower().strip()` on write + `test_charter_writes_lowercased_aliases` |
| **Alias row written before the domain row** → `to_path` points at a non-existent domain and `normalize_domain_label` returns it anyway | Task 5, Step 4 | domain row created first, ordering documented in the route docstring |
| **Behaviour drift with no charter present** | Task 3 | `test_ingest_route.py` must pass **unmodified** — final verification checks `git diff` on that file |
| **Schema drift between the two `db.py` files** | Task 1 | both edited in the same commit; `test_schema_mirror.py` in the suite |

---

## Known limitations (accepted, not deferred bugs)

- **No UMAP anchor** for charter domains — `anchor_paths()` reads `taxonomy.json` only, so a
  charter domain sits poorly on the galaxy map. Cosmetic. Fix is the taxonomy overlay that §5
  deliberately excludes.
- **Steering is weaker than the reference vocabulary.** A charter domain reaches the classifier
  via the existing-taxonomy block, whose prompt says "reuse ONLY when it is the SAME topic; it
  is NOT a preference." Aliases are the backstop. If invented paths keep escaping the alias
  list, that is the evidence that justifies building the overlay.
- **One expert, one domain.** Nothing prevents several charters, but the conversation is not
  designed for it.
- **Editing a charter does not re-extract existing documents.** `extract_batch` exists and
  could be queued; not in scope.

---

## Next action

**Start Task 1.** Create a branch first — the current branch is `feature/onboarding-tutorial`
and unrelated:

```bash
git checkout -b feature/domain-charter
cd orchestrator && pytest tests/ -q   # confirm green before starting
```
