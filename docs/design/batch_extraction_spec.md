# Batch Extraction UI — Implementation Spec

## Where it lives

New page: `/extraction/{job_id}`

Entry points:
- `/pipeline` active jobs list → `extract_batch` job row links here
- `/pipeline` active jobs list → `extract_batch` job row links here
- `/simmer/{job_id}` completed state → CTA: "extraction ran · {N} entities found · view results →"
- Future: `/pipeline` doc row status badge "extracted" links to the batch that extracted it

---

## API changes needed before building

### 1. `is_new` flag on entities (required)

**Request:** Add `is_new: bool` to every entity object returned by `GET /entities`.

**Derivation:** `entity.created_at` falls within the job's `started_at → completed_at` window. Pure DB logic, no new tracking.

**Why it matters:** Powers the "new only" filter tab and the `+N new` headline stat. Without it the entity grid has no way to answer "what did this batch actually discover."

### 2. Batch results summary on job (required)

Add to `GET /jobs/{id}` response:

```json
{
  "entities_found": 247,
  "entities_new": 31,
  "entities_matched": 216,
  "docs_processed": 20,
  "spec_version": "general_v2"
}
```

Derivable from existing data at job completion time. Powers the stat strip without paginating all entities to count them.

### 3. Per-doc entity list (nice to have, not blocking)

`GET /documents/{id}?job_id={job_id}` — filter entities to those extracted during a specific job.

Currently `GET /documents/{id}` returns all entities ever associated with a doc. For the per-doc view we need entities extracted *in this batch specifically*. If this is too complex to scope now, the per-doc filter can be approximated by filtering `entity.sources` where `extraction_pass` matches the job — but a clean query param is preferable.

---

## Data sources

```
GET /jobs/{id}                  → job metadata + new results summary fields
GET /documents                  → [{id, title, status, domains, entity_count}]
GET /documents/{id}             → doc with entities (optionally filtered by job_id)
GET /entities?type=X            → [{id, canonical_name, type, source_count, is_new}]
GET /normalize/summary          → {merges_by_method, total_merges, pending_reviews}
```

Poll `GET /jobs/{id}` every 5s while `status === "running"`. Stop when `completed | failed`.

---

## Component hierarchy

```
ExtractionPage
├── ExtractionHeader
├── StatStrip
└── MainLayout (two-column)
    ├── DocList (left, fixed ~220px)
    │   └── DocRow × N
    └── RightPane (fills remaining)
        ├── EntityPanel
        │   ├── EntityPanelHeader (title + filter tabs)
        │   └── EntityGrid
        │       └── EntityCard × N
        └── BottomRow (two-column)
            ├── TypeDistribution
            └── NormalizationSummary
```

---

## Component specs

### ExtractionHeader

```
┌──────────────────────────────────────────────────────────────┐
│ jobs / {job_id_short} · extract_batch · {spec_version}       │
│ Batch extraction · {doc_count} documents                      │
│ completed in {duration} · spec: {spec_version} · haiku-3-5   │
│                                                  [● completed]│
└──────────────────────────────────────────────────────────────┘
```

- `job_id_short` = first 8 chars of job_id
- `spec_version` = `general_v2` | `domain/{path}_v1` etc — from new job results field
- `duration` = `completed_at - started_at` formatted as "4m 12s"
- Badge states:
  - `running` → amber pulsing dot + "extracting"
  - `completed` → green dot + "completed"
  - `failed` → red dot + "failed · {N} docs failed"

---

### StatStrip

Five cells, full width, single border container.

```
┌──────────────┬──────────────┬──────────────┬──────────────┬──────────────┐
│ 20           │ 247 +31 new  │ 7            │ 14           │ 4m 12s       │
│ DOCS         │ ENTITIES     │ TYPES        │ MERGES       │ DURATION     │
│ all extracted│ 216 matched  │ Person·Org…  │ after norm.  │ 12.6s avg    │
└──────────────┴──────────────┴──────────────┴──────────────┴──────────────┘
```

Fields:
- **Docs:** `jobs.docs_processed` / sub: "all extracted" or "{N} failed" in danger color
- **Entities:** `jobs.entities_found` with `+{jobs.entities_new} new` in success color inline / sub: `{jobs.entities_matched} matched existing`
- **Types:** count of distinct entity types found / sub: first 3 type names abbreviated
- **Merges:** `normalize/summary.total_merges` / sub: "after normalization"
- **Duration:** formatted duration / sub: avg per doc (`duration / docs_processed`)

If `entities_new === 0`, omit the `+0 new` and just show the total with sub "all matched existing" in tertiary color.

While job is running: replace entity/merge stats with animated placeholder, docs cell shows live count incrementing.

---

### DocList

Left column, vertically scrollable.

```
┌─────────────────────────┐
│ DOCUMENTS    20 docs    │  ← header
├─────────────────────────┤
│ q3-planning.txt         │  ← active: 2px left border info color
│ business/strategy   31  │
│ [████████████████░░░]   │  ← bar = entity count relative to max in batch
├─────────────────────────┤
│ investor-call-oct.txt   │
│ business/finance    28  │
│ [███████████████░░░░]   │
├─────────────────────────┤
│ product-roadmap.txt     │
│ business/product    24  │
│ [█████████████░░░░░░]   │
└─────────────────────────┘
```

Per row:
- Doc `title` (truncated with ellipsis)
- `domains[0]` path truncated + `entity_count` right-aligned
- Thin bar: width = `entity_count / max(entity_count across all docs in batch) * 100%`

Interactions:
- Click row → filters EntityGrid to entities from that doc only, updates panel title
- Click active row again → deselects, returns to all-entities view
- Active row: 2px left border in info color

States:
- Doc `status === "extracted"` → normal
- Doc `status === "classified"` (not yet extracted, running job) → row dimmed, entity count shows "—", bar empty, pulsing dot

Sort: by `entity_count` descending by default.

---

### EntityPanel

Full-width panel in the right pane.

#### EntityPanelHeader

```
┌─────────────────────────────────────────────────────────────────┐
│ All entities · 247   [all] [new] [person] [org] [product] [tech]│
│                      [event] [concept] [location]               │
└─────────────────────────────────────────────────────────────────┘
```

- Title updates when doc is selected: `{doc_name} · {N} entities`
- Filter tabs: `all`, `new` (is_new === true), then one per entity type found in batch
- `new` tab only shown if `entities_new > 0`
- Active tab: info color border + background
- Tabs are additive with doc selection — doc filter + type filter both apply simultaneously

#### EntityGrid

CSS grid, `repeat(auto-fill, minmax(180px, 1fr))`, 1px gap (border color background).

```
┌───────────────────┐  ┌───────────────────┐
│ Sarah Chen        │  ┃ DataSync Pro      │  ← new: 2px left border success color
│ [Person]    8 docs│  ┃ [Product]  new·6  │
└───────────────────┘  └───────────────────┘
┌───────────────────┐  ┌───────────────────┐
│ Orbit Dashboard   │  │ Sequoia Capital   │
│ [Product]   9 docs│  │ [Org]      new·3  │
└───────────────────┘  └───────────────────┘
```

Per card:
- `canonical_name` (truncated)
- Type badge: colored per type (see color mapping below)
- If `is_new === true`: green left border (2px) + "new" tag before source count
- `source_count` + "docs" label

Sort default: new entities first, then by source_count descending.

Click card → navigate to `/entities/{id}` (existing entity detail page).

Type badge color mapping (bg / text — use hardcoded for dark mode consistency):
```
Person:       bg #1a2a3a  text #378ADD
Organization: bg #2a1f2a  text #7F77DD
Product:      bg #1a2a24  text #1D9E75
Technology:   bg #2a251a  text #BA7517
Event:        bg #2a1a1a  text #D85A30
Concept:      bg #1e1e2a  text #9c9a92
Location:     bg #1a2420  text #5DCAA5
```

Empty state (no entities match filter):
```
┌────────────────────────────────────────┐
│                                        │
│   no entities of this type in batch    │
│                                        │
└────────────────────────────────────────┘
```

---

### BottomRow

Two equal columns below the entity panel.

#### TypeDistribution

```
┌─────────────────────────────────────────┐
│ ENTITY TYPE DISTRIBUTION                │
├─────────────────────────────────────────┤
│ Person        [████████████░░░] 68  +4  │
│ Organization  [██████████░░░░░] 52  +3  │
│ Product       [█████████░░░░░░] 47  +11 │
│ Technology    [███████░░░░░░░░] 38  +7  │
│ Concept       [████░░░░░░░░░░░] 22  +4  │
│ Event         [██░░░░░░░░░░░░░] 14  +2  │
│ Location      [█░░░░░░░░░░░░░░]  6  —   │
└─────────────────────────────────────────┘
```

Per row:
- Type name (fixed width ~90px)
- Bar: width = `count / max_count * 100%`, colored per type
- Count right-aligned
- New count: `+{N}` in success color, or `—` in tertiary if 0

Bar opacity 0.7 to keep it readable against dark background.

Clicking a type row → applies that type filter to the entity grid above (same as clicking the tab).

#### NormalizationSummary

```
┌──────────────────────────────────────────┐
│ NORMALIZATION                            │
├──────────────────────────────────────────┤
│ Plural collapse          6               │
│ entities → entity                        │
├──────────────────────────────────────────┤
│ Embedding similarity     5               │
│ ≥ 0.92 cosine                            │
├──────────────────────────────────────────┤
│ Manual review            [review →]      │
│ 3 pending                                │
└──────────────────────────────────────────┘
```

Fields from `GET /normalize/summary`:
- `merges_by_method.plural` → plural collapse count
- `merges_by_method.embedding` → embedding similarity count
- `pending_reviews` → manual review count + action button

"review →" button navigates to the existing normalize review queue on `/pipeline` (or wherever it lives). Only show if `pending_reviews > 0`. If `pending_reviews === 0`, show "0 pending" in tertiary color with no button.

If `total_merges === 0` across all methods: show a single row "no merges — all entities distinct" in tertiary color.

---

## Page states

### Running (job in progress)

- Header badge: amber pulsing "extracting"
- StatStrip: docs cell increments live, entities/merges show "—" until complete
- DocList: completed docs render normally, pending docs show dimmed with "—" count
- EntityGrid: shows entities found so far, new ones append with fade-up animation
- Poll every 5s

### Completed

- Stop polling
- All stats populated
- Header badge: green "completed"
- Full entity grid rendered, sorted new-first

### Failed

- Stop polling
- Header badge: red "failed"
- StatStrip: docs cell shows "{N} / {total} · {failed} failed" with failed count in danger color
- Failed doc rows in DocList get danger left border
- Show inline error message in entity panel: "extraction failed for {N} docs — partial results shown"

### Empty (0 entities found)

Unlikely but handle it:
- EntityGrid shows: "no entities extracted — check spec configuration"
- Link to the simmer job that produced the spec

---

## Fitting into existing pages

### `/pipeline` active jobs list

```
Before:
[extract_batch]  general  running  started 2m ago

After:
[extract_batch]  general v2  running · 14/20 docs  [↗ view extraction]
```

- Job row shows live doc progress count while running
- Links to `/extraction/{job_id}` when clicked or via the arrow link

### `/simmer/{job_id}` completed state

Add a completion footer below the iteration list:

```
┌──────────────────────────────────────────────────────┐
│ Spec converged · v2 saved                            │
│ Extraction ran immediately after · 20 docs           │
│ 247 entities found · +31 new    [view extraction →]  │
└──────────────────────────────────────────────────────┘
```

Only show if an `extract_batch` job exists with this simmer job's spec version. Link to `/extraction/{extract_job_id}`.

### `/entities` page

No changes required for v1. Future: add a "first seen" column showing which batch introduced each entity.

---

## What does NOT need to change

- Galaxy viz — no changes
- Simmer page — only the completion footer addition above
- Entity detail page `/entities/{id}` — entity cards link to it as-is
- Normalization review queue — normalization panel links to it as-is
