# Batch Extraction UI — Spec for Design Agent

**Date:** 2026-03-28
**Context:** After a simmer run completes, an `extract_batch` job runs that extracts entities from all docs using the simmered spec. Currently this is invisible — there's no way to see what was extracted, from which docs, or what the spec found.

## What Data Is Available

### From the API

**Job info:** `GET /jobs` returns extract_batch jobs with status, timestamps.

**Documents:** `GET /documents` returns each doc with:
- `status`: classified → extracted → enriched
- `entity_count`: how many entities were found
- `domains`: which domains it's assigned to

**Entities:** `GET /entities` returns all entities with:
- `canonical_name`, `type` (Person, Organization, Product, etc.)
- `source_count` — how many docs mentioned this entity

**Entity detail:** `GET /entities/{id}` returns:
- `sources`: [{document_id, chunk_id, extraction_pass}] — which doc and chunk produced this entity
- `merge_history`: names that merged into this one

**Normalization:** `GET /normalize/summary` returns merge counts by method.

### What's NOT Available Yet (could add)

- **Per-doc extraction results** — which entities were found in each doc during a specific batch run
- **Extraction timing** — how long each doc took
- **Spec used** — which spec version was applied (stored in entity_sources.spec_version but not exposed as a filter)
- **New vs existing** — whether an extracted entity was new or matched an existing one

## What Would Be Useful to See

### 1. Batch Run Summary
When an extract_batch job completes, show:
- How many docs were processed
- How many entities found (new vs existing matches)
- How many normalization merges happened
- Which entity types were most common
- Duration

### 2. Per-Document View
For each doc in the batch:
- Doc title
- Entities extracted (with types)
- Domains assigned
- Status change (classified → extracted)

### 3. Entity Discovery Timeline
As a corpus grows, show what entities appeared over time:
- New entities per batch
- Entity type distribution shifts
- Which batches found the most new entities

### 4. Spec Effectiveness
Compare extraction quality across spec versions:
- General spec v1 found X entities
- Domain spec v1 for `business/fundraising` found Y additional entities
- Overlap / unique entities per spec

## Current API Endpoints

```
GET  /stats                     → {document_count, entity_count, domain_count, active_jobs}
GET  /documents                 → [{id, title, status, domains, entity_count}]
GET  /documents/{id}            → doc with entities list
GET  /entities?type=X&domain=Y  → [{id, canonical_name, type, source_count}]
GET  /entities/{id}             → entity with sources and merge_history
GET  /jobs                      → [{id, type, target, status, timestamps}]
GET  /normalize/summary         → {merges_by_method, total_merges, recent_merges}
GET  /graph                     → cosmic viz data format
```

## Relationship to Other Pages

- **Pipeline page** shows active/recent jobs — extract_batch jobs should link somewhere useful
- **Entities page** is a flat table — could show batch provenance (which run added this entity)
- **Simmer page** shows simmer runs — extract_batch is the next step after simmer completes
- **Galaxy viz** shows the final graph — extraction is how entities get there

## Design Constraints

Same as other pages: dark mode, monospace, muted with bright accents, Tailwind 4, shadcn/ui components. The extraction view should feel like a natural continuation of the simmer view — you watch the spec get built, then you see what it found.
