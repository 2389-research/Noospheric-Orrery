# Contracts Charter — Spec Evaluation Design

Date: 2026-08-21 · Base commit: `833eb05` · Author: yi

## Problem

`business/legal-compliance/contracts` has an authored charter (spec version 1, written
2026-08-21). It works in the mechanical sense — 13/13 declared types fire, zero off-spec
types across four runs — but it produces **522 entities from one commercial lease**, of
which **228 are `obligation`**. For scale: the entire existing graph is 169 entities.

The defect is not volume. It is **shape**. Observed `obligation` names:

```
"tenant may renew this lease for five additional successive one-year terms
 at a monthly rent of $100,000 per month"
"if payment is not postmarked or received by landlord on or before the tenth
 day of each month"                                        (condition_trigger)
```

These are sentence-length unique strings. The Orrery graph model assumes entities that
**recur across documents** — that assumption is what `merge_map`, `normalizer.py`,
`embedding_normalizer.py`, and `cooccurrence.py` all exist to exploit. A node that
appears in exactly one document, forever, is an annotation, not a graph entity. Two of
the thirteen declared types (`obligation`, `condition_trigger`) appear to be spans
wearing an entity costume.

The other eleven look correct precisely because they recur: `clause: "indemnification"`
appears in every contract; `governing_law: "california"` recurs; `monetary_term:
"security deposit"` recurs; `party: "okra energy, inc. (tenant)"` recurs across
amendments to the same deal.

## Question

Ship variant **A** or variant **B**?

| Variant | Change from v1 | Predicted entities/lease |
|---|---|---|
| **A** | Delete `obligation` and `condition_trigger`. 11 types. | ~215 |
| **B** | Keep all 13, add a naming rule forcing short canonical obligation names — `<party> — <duty>`, ≤6 words, e.g. `"tenant — pay monthly rent"`. | ~300 |

B is worth testing rather than assuming, because `obligation` is the **only reason the
charter was justified in the first place**: the general spec structurally cannot emit it
(its four extraction conditions — proper noun / defined-in-text / mentioned-2+-sentences
/ has-a-numeric-value — never reach a provision containing no name and no number). Drop
`obligation` and the step-8 `added` set shrinks toward the point where the general spec
plus a simmer would have done.

## Scope

### Out of scope — already covered

**Pipeline wiring needs no new tests.** All four charter hook points are already tested,
and re-testing them would be pure duplication:

- `orchestrator/tests/test_charter_route.py` — domain row + parent path, lowercased
  alias rows, alias resolution through `normalize_domain_label`, authored spec written,
  `spec_version` set (auto-simmer disabled), version bump on re-POST, self-referential
  alias skipped, 201 + `Location`, `GET` 404.
- `orchestrator/tests/test_extraction_plan.py` — authored suppresses general, simmered
  does not, ancestor application, dedup by spec id, deepest-first, latest-version-wins.
- `orchestrator/tests/test_domain_normalizer.py` — merge-map hit, new-domain insert.

### In scope

Evaluating **spec quality**, which nothing currently tests and which `pytest` structurally
cannot test: it needs a live LLM, costs ~126s per document, and is nondeterministic.

## Enabling fact

`POST /ingest?dry_run=true` runs the **real** classifier and the **real** extractor with
the **real** charter spec, and writes nothing — no `documents` row, no `chunks`, no
`entities`, no `document_domains`. Verified 2026-08-21: after five dry-runs the workspace
DB had zero rows for either test contract.

So the harness exercises the production path at zero cost to the graph. No fixtures, no
mocks, no staging database.

## Metrics

All computed per type, so a decision can be made about `obligation` specifically rather
than about the spec as a whole.

| ID | Metric | Definition | Why |
|---|---|---|---|
| **M1** | **mergeability** | fraction of distinct entity names for that type appearing in ≥2 corpus documents | The core question. A type that never recurs is not a graph entity. |
| **M2** | name length | median words per entity name | Span-vs-entity proxy. Entity-shaped ≈ ≤4 words. |
| **M3** | volume | entities per document | Graph bloat. |
| **M4** | type stability | mean Jaccard of the *fired-type set* across R repeats of one document | Detects a spec too complex to follow. **Measured at 1.00 for v1** (3 repeats, sublease template). |
| **M5** | count variance | coefficient of variation of per-type counts across R repeats | Boundary-judgment noise. v1: ±7% total, concentrated in `clause`/`obligation`. |
| **M6** | precision | human-labelled correct / (correct + incorrect), stratified sample | The only way to catch type-confusion. Two suspected v1 errors already: `organization: "supervising architect"` (a role, not an organization) and `document: "fire and extended coverage insurance policies"` (not an external instrument). |
| **M7** | latency | seconds per document | v1: 126s/lease vs 53s general. |

## Corpus requirement — the current corpus cannot answer the question

**M1 requires cross-document name overlap.** The existing two documents
(`lease.txt`, `sublease-agreement.docx`) are one executed lease and one blank template,
of different instrument types. Mergeability across them is near-meaningless: any overlap
would be coincidence, and any non-overlap would be explained by instrument difference
rather than by name shape.

Minimum corpus for a decision:

| Instrument | Executed | Template/unexecuted | Why |
|---|---|---|---|
| Lease | 3 | 1 | Have 1 executed + 1 sublease template. Need ≥3 same-instrument for M1. |
| NDA | 3 | 0 | Shortest, most templated instrument — the strongest merge signal, and completely untested. |
| MSA / SOW | 2 | 0 | Tests whether `subject_property` degrades gracefully on a non-real-property instrument. |
| Amendment | 1 | 0 | Only instrument where the *same* `party` should recur across documents. |

**Source: SEC EDGAR full-text search, `EX-10` exhibits** (material contracts). Public,
free, legally clear, and already the provenance of `lease.txt` (its first line is
`EX-10 2 elmonteleaseforfiling.htm MATERIAL CONTRACT`). Leases, NDAs, MSAs, and
amendments are all filed as EX-10.

Corpus documents are regenerable artifacts and per the `experiments/README.md` convention
live **outside this repo** in DS-scratch, referenced by manifest, not committed.

## Pre-registered decision rule

Written before running, and deliberately not to be moved afterwards. The 0.30 threshold
is a judgement call, stated up front so it cannot be adjusted to fit the result.

**Ship B** if, on the `obligation` type, all three hold:

1. **M1 ≥ 0.30** — at least 30% of obligation names recur in 2+ documents
2. **M2 ≤ 6 words** — the naming rule actually bound the model
3. **M6 ≥ 0.80** — shortening did not destroy meaning

**Otherwise ship A.**

If B fails only on M2, the failure mode is instructive: it means a naming rule cannot
constrain generated names, and no rewording will fix it. Do not iterate on the wording
more than once.

## Non-goals

- Not tuning `clause`/`obligation` boundary variance (M5). ±7% is acceptable; downstream
  normalization exists to absorb it.
- Not measuring recall against a hand-annotated gold contract. Valuable, expensive,
  and not needed to choose between A and B.
- Not touching `orchestrator/specs/general_text.md`.
- Not evaluating any domain other than contracts.
