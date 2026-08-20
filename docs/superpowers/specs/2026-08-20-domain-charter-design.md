# Domain Charter — letting an expert bind their opinion into the pipeline

Date: 2026-08-20
Status: proposed

## Problem

The pipeline derives everything from LLM inference: the classifier picks a domain from
`taxonomy.json` plus whatever paths already exist in the graph, and the extraction spec for
a domain is produced by a simmer job that only runs once the domain has 20 documents.

For a user whose domain the system already knows — a software team — this works. For a
domain expert whose field is barely represented, it fails at the cold start, and it fails
in a way that does not heal:

- `taxonomy.json` gives a lawyer four topics (`business/legal-compliance`:
  `contracts, intellectual-property, privacy-compliance, corporate-governance`) out of 199,
  of which 107 are software. The reference vocabulary does not cover them.
- The classifier is explicitly permitted to invent a path when nothing fits, and does.
  `normalize_domain_label` creates whatever string comes back as a real domain row with no
  validation against the taxonomy.
- Early inventions become the graph's vocabulary, because later documents see them in the
  existing-taxonomy block. Drift compounds.
- `document_count` is per exact path string, so documents scattered across
  `legal/contracts`, `business/legal-compliance/contracts` and `contracts` split the count
  three ways. The `domain_spec_threshold` of 20 may never be reached — not for lack of
  documents, but because they never land on one path.
- Even when it is reached, documents 1–20 were extracted with the general spec and nothing
  re-extracts them.

The expert has the knowledge that would fix all of this on document one. There is currently
no way for them to state it.

## Solution

A **charter**: a declaration, produced by a guided conversation with Claude, that an expert
writes once before ingesting anything. It contains their canonical domain path, the aliases
that should fold onto it, and their extraction spec.

The charter needs no new pipeline stage. It writes into three slots that already exist:

| Declaration | Slot | Mechanism |
|---|---|---|
| "this is my domain" | `domains` row | appears in the classifier's existing-taxonomy block from document 1 |
| "these names mean the same domain" | `domain_merge_map` | `normalize_domain_label` checks it **first**, before anything else |
| "these are my extraction rules" | `specs` row, `source='authored'` | the cascade calls `store.specs.get_for_domain()` and does not care where the row came from |

The third is the cold-start fix. The 20-document wait exists only to *generate* a spec. An
authored spec means there is nothing to wait for.

## The authored/simmered contract split

This is the central finding of the design investigation, and the constraint everything else
follows from.

`simmer_domain` is **additive by design**. Its own comments say so
(`worker/src/jobs/simmer_domain.py:20`, `:131-134`, `:158-159`): it discovers *more granular*
domain-specific types and extracts only those, because "base types are covered by the general
pass." If it discovers no domain-specific types it skips entirely rather than storing a spec
(`:146-150`).

A simmered domain spec is therefore **incomplete on purpose** — it depends on the general
pass at `ingest.py:116` running alongside it.

An authored spec is the opposite. The user's requirement is "if it's a contract, use my rules,
otherwise use the general spec" — meaning for contracts, their spec runs *instead of* the
general pass. An authored spec must be **complete and self-contained**.

Two different contracts on the same table:

| | contract | general pass |
|---|---|---|
| `source='simmered'` | additive — granular types only | **must** run |
| `source='authored'` | complete — self-contained | **suppressed** |

`specs.source` therefore carries the *contract*, not merely provenance. Suppressing the general
pass for a simmered spec would silently drop every base type. Running it alongside an authored
spec would reintroduce exactly the noise the expert excluded.

## Design

### 1. The extraction rule

> The general pass is skipped only for documents whose resolved spec set contains an authored
> spec.

- a contract resolves to the authored spec → only that spec runs
- anything else resolves to nothing authored → general pass runs, exactly as today
- that one sentence is the whole "if contract → mine, otherwise → general" behaviour

Edge cases, stated so they are not rediscovered:

- **Authored primary + simmered secondary** → both specs run, general does not. The authored
  spec suppresses the *general* pass, not other domain specs. The simmered spec loses the base
  types it assumed; this is accepted, because the authored spec is the user's declared
  authority for that document.
- **No authored spec anywhere** → byte-identical to today's behaviour.

### 2. Pipeline change (`orchestrator/src/routes/ingest.py`)

Today the ancestor walk is inline in step 4, *after* the general pass at step 3 has already run.
The decision must be made before step 3.

Extract `resolve_extraction_plan(store, domains) -> (run_general: bool, specs: list[Spec])`:

- walk each domain's ancestors deepest-first, dedup by spec id — same logic as today's `seen_specs`
- `run_general = not any(s.source == 'authored' for s in specs)`
- call it immediately after `assign_document_domains` (`ingest.py:105`)
- step 3 becomes conditional on `run_general`; step 4 iterates the returned list

This also improves the existing code: the ancestor walk stops being buried mid-function and
becomes independently testable.

### 3. Schema

One column:

```sql
ALTER TABLE specs ADD COLUMN source TEXT DEFAULT 'simmered'
```

- follows the existing migration pattern (`db.py:311`, `media_type`)
- default `'simmered'` means every existing row keeps today's behaviour
- must land in **both** `orchestrator/src/db.py` and `worker/src/db.py` — the schema mirror
  test enforces identity
- add `source` to the `Spec` dataclass (`repositories/interfaces.py:97`) and to
  `SpecRepository.create()`

### 4. Endpoints — two changes, one of them a parameter

**`POST /ingest` gains `dry_run: bool`.** Classifies and extracts, returns both, persists
nothing. Not a new endpoint. This is what the skill drives the conversation from.

**`POST /charter`** — one payload, three writes, one transaction:

```json
{
  "domain": "business/legal-compliance/contracts",
  "aliases": ["legal/contracts", "contracts", "legal/agreements"],
  "spec": "<markdown extraction spec>"
}
```

Writes, in order:

1. the canonical `domains` row (must exist before step 2 — `domain_merge_map.to_path`
   references it, and `normalize_domain_label` returns `to_path` without checking the domain
   exists)
2. `domain_merge_map` rows, one per alias
3. the `specs` row: `domain_path=domain`, `version=1`, `source='authored'`
4. `domains.spec_version = 1` for the canonical path

`GET /charter` reads it back for editing.

Step 4 is load-bearing for decision (b) — see below.

### 5. No taxonomy overlay, and why

The obvious design is a per-workspace overlay merged into `taxonomy.json` so the user's
vocabulary reaches the classifier's REFERENCE VOCABULARY block. It is not in this design.

Creating the `domains` row puts the path into `store.domains.get_all_paths()`, which is
already rendered into the classifier's existing-taxonomy block on document one. That is free.
An overlay would require passing a taxonomy dict into `classify_document`, which means editing
`orchestrator/src/pipeline/classifier.py` **and** `worker/src/classifier.py` in byte-identical
lockstep plus the mirror test, and inventing per-workspace overlay storage for a globally
cached, workspace-blind loader.

The existing-taxonomy block steers more weakly than the reference vocabulary — its prompt says
"reuse a path from here ONLY when it is the SAME topic; it is NOT a preference." But the
aliases in `domain_merge_map` catch what weak steering misses: the classifier invents
`legal/contracts`, and the merge map folds it onto the canonical path before it is ever stored.
Steering plus correction should be sufficient.

**Escalation path if it is not:** add the overlay, in its own change, once there is evidence
of paths being invented that the alias list does not catch.

**Known limitation, accepted:** `anchor_paths()` reads `taxonomy.json` only, so a charter
domain gets no UMAP anchor and sits poorly on the galaxy map. Cosmetic, deferred, and the
fix is the same overlay.

### 6. Simmer seeding (decision b)

Requirement: an authored spec is never silently overwritten, and refinement keeps the user's
entity types while improving the wording.

**Auto-simmer disables itself for free.** `ingest.py:189` requires `domain.spec_version IS NULL`
to queue a `simmer_domain` job. Writing `spec_version = 1` in `POST /charter` makes that false
forever. No code change. Refinement happens only when the user explicitly calls the existing
`POST /simmer/{domain_path}`.

**Worker changes** (`worker/src/jobs/simmer_domain.py`):

- **Seed from the authored spec.** At `:46-92` the seed is built from the general spec. When an
  authored spec exists for the domain, its content becomes the seed instead, and the golden-set
  taxonomy is the user's declared entity types rather than `_discover_domain_types` output.
- **Preserve the complete contract.** The refined output must be stored with
  `source='authored'`, and the refinement must be told to produce a *complete* spec, not an
  additive one. This is a mode flag on the job, not just a different seed — getting it wrong
  means the refined spec becomes additive, the general pass switches back on, and the user's
  exclusions silently stop working.
- **Constrain the judge.** The declared entity types are appended to the judge prompt as
  constraints. Appended to `build_judge_prompt`, never replacing it — see CLAUDE.md invariant 5.
- **Skip the empty-discovery early return.** `:146-150` returns early when no domain-specific
  types are discovered. With an authored seed there is nothing to discover; the types are given.

`simmer_domain` requires sample chunks and raises without them (`:41`), so refinement is
inherently post-cold-start. That is correct — there is nothing to refine against on day one.

`simmer_domain` already queues an `extract_batch` on completion (`:188`), so documents ingested
under the authored spec are re-extracted under the refined one automatically.

### 7. The skill

A new skill. (`design-your-orrery` exists and overlaps, but is not to be used or extended.)

The conversation is built on one principle: **experts critique output fluently and prompts not
at all.** It never asks the user to author an ontology from a blank form. It shows them what the
system would do and lets them correct it.

Flow:

1. **Ask what they work on.** Free text. "Contracts — NDAs, MSAs, SOWs."
2. **Check the existing taxonomy first.** `business/legal-compliance/contracts` already exists.
   Propose reusing it. Reuse is what lets their content merge with anything else in the graph;
   inventing a new region is the failure mode, not the feature.
3. **Ask them to drop one real document.**
4. **Dry-run it** via `POST /ingest {dry_run: true}` — one classify call, one extract call,
   nothing written.
5. **Present the first pass as it actually is:**
   - "I'd file this as `business/legal-compliance/contracts`"
   - "I'd extract these types" — each with a count and 2–3 real instances from their document
6. **They correct.** This is the whole point of the exercise.
   - is the path right? what other names should fold onto it? → `aliases`
   - which types matter, which are noise, what is missing entirely? → `spec`
7. **Second document.** The first correction round always overfits to one sample. This step is
   not optional.
8. **Worth-it analysis** (below).
9. **Show the charter and confirm** before any write. Nothing is persisted until they say yes.

### 8. Worth-it analysis

The skill must be willing to conclude that a charter is not worth writing. A skill that always
recommends its own artifact is useless as advice.

Compare the user's corrected type set against what the general spec actually produced in the
dry run:

- **`added`** — types they want that the general spec never emitted
- **`dropped`** — types it emitted that they rejected
- **`kept`** — the overlap

Recommendation:

- **`added` is non-empty → write the charter.** The general spec structurally cannot produce
  those types. No amount of waiting or simmering fixes it.
- **`added` empty but `dropped` > half → write the charter.** Precision is the entire benefit,
  and since an authored spec replaces the general pass, the noise genuinely disappears.
- **Otherwise → recommend the general spec, write nothing.** Say so plainly: "your edits were
  minor, the general spec already covers this, a charter is maintenance you don't need."

## Testing

- `resolve_extraction_plan` unit tests: no specs; simmered only; authored only; authored primary
  plus simmered secondary; authored at an ancestor of the classified path
- **The no-opinion guarantee:** existing ingest tests pass **untouched**. That is the proof that
  behaviour without a charter is unchanged
- `POST /charter`: writes all four things in one transaction; rolls back cleanly on a bad alias
- `POST /ingest {dry_run: true}`: returns classification and entities, and persists nothing —
  assert the document, chunk, entity and domain tables are all still empty afterwards
- Migration: an existing DB with rows gets `source='simmered'` and behaves identically
- Schema mirror test still passes after the column lands in both `db.py` files (must run natively)

## Open items, deliberately deferred

- **UMAP anchors** for charter domains — needs the taxonomy overlay
- ~~Alias normalisation inconsistency~~ — **resolved during design review.** Both lookup paths
  normalise identically: `domain_normalizer.py:22` and `sqlite_store.py:278` each apply
  `.lower().strip()` to `from_label`. Charter aliases must therefore be **stored lowercased and
  stripped**, or they will never match
- **Multiple charters per workspace** — the design assumes one expert, one domain. Nothing
  prevents several charters, but the conversation is not designed for it
- **Editing a charter after documents exist** — `GET`/`POST` allow it, but nothing re-extracts
  the affected documents. `extract_batch` exists and could be queued; not specified here

## Sequencing

1. `specs.source` column and migration, both `db.py` files, `Spec` dataclass, repository
2. `resolve_extraction_plan` and the ingest rewiring — ships alone, changes nothing without a
   charter
3. `POST /ingest {dry_run}`
4. `POST /charter` + `GET /charter`
5. The skill
6. `simmer_domain` authored-seed mode — last, because it is only reachable after a charter
   exists and documents have been ingested
