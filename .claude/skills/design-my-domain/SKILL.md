---
name: design-my-domain
description: Use when a Noospheric Orrery user is an expert in one domain (contracts, clinical notes, incident reports) and wants their own judgment to govern classification and extraction from the first document, instead of the generic spec. Runs a guided conversation over one of their real documents and writes a charter.
---

# Design My Domain

Turn a domain expert's opinion into a charter the pipeline obeys from document one.

## Why this exists

The classifier's reference vocabulary (`orchestrator/specs/taxonomy.json`) has 199 topics, 107
of them software. A lawyer's entire field is four topics. Off-taxonomy users get invented domain
paths that fragment across near-duplicates, so `document_count` never reaches the 20 needed to
trigger a domain simmer — they can wait forever and never get a spec.

A charter skips all of that: it declares the domain, the aliases that fold onto it, and the
extraction spec, so extraction is right on the first document.

## The one rule

**Never ask the user to write an ontology from a blank form.** Experts critique output fluently
and prompts not at all. Show them what the system would actually do, and let them correct it.

## Process

### 1. Ask what they work on

One question, free text. "Contracts — mostly NDAs and MSAs."

### 2. Look for an existing home in the taxonomy

Read `orchestrator/specs/taxonomy.json` and find the closest existing path.
`business/legal-compliance/contracts` already exists.

**Propose reusing it.** Reuse is what lets their content merge with everything else in the
graph. Inventing a new top-level region is the failure mode, not the feature. Only propose a
new path if nothing in the file is close.

### 3. Ask them to drop in one real document

A real one, not a sample you invent. The whole method depends on them reacting to their own
material.

### 4. Dry-run it

    curl -s -X POST "$ORRERY_API/ingest?dry_run=true" -F "file=@<their-file>"

This classifies and extracts and writes nothing — no document row, no chunks, no entities, and
no domain rows.

### 5. Show them the first pass

Present exactly two things:

- **"I'd file this as `<primary_domain>`"** — plus any secondaries
- **"I'd extract these types"** — every type with its count and 2-3 real instances from
  their document

Show the instances. `Date — 47 instances: "January 3, 2024", "the 15th day", "upon signing"`
provokes a useful reaction; `Date — 47` does not.

### 6. Collect their corrections

Two questions, asked separately:

- **Is the path right?** What other names should fold onto it? Their answer becomes `aliases`.
  Push for the near-duplicates a classifier would plausibly invent — `legal/contracts`,
  `contracts`, `legal/agreements`.
- **Which types matter?** What is noise, what is missing entirely? Their answer becomes the
  spec.

### 7. Validate on a second document

Not optional. The first round always overfits to one sample. Dry-run a second document and
show what their corrected type list would have missed.

### 8. Run the worth-it analysis

Compare their corrected type set against what the general spec actually produced:

- **`added`** — types they want that the general spec never emitted
- **`dropped`** — types it emitted that they rejected
- **`kept`** — the overlap

Then recommend:

- **`added` is non-empty → write the charter.** The general spec structurally cannot produce
  those types. Waiting does not fix it.
- **`added` empty but `dropped` > half → write the charter.** An authored spec replaces the
  general pass, so the noise genuinely disappears.
- **Otherwise → recommend the general spec and write nothing.** Say it plainly: "your edits
  were minor, the general spec already covers this, a charter is maintenance you don't need."

**Be willing to reach the third conclusion.** A skill that always recommends its own artifact
is useless as advice.

### 9. Show the charter and get explicit confirmation

Print the full payload. Nothing is written until they say yes.

    curl -s -X POST "$ORRERY_API/charter" -H 'Content-Type: application/json' -d '{
      "domain": "business/legal-compliance/contracts",
      "aliases": ["legal/contracts", "contracts", "legal/agreements"],
      "spec": "# Contract extraction\n..."
    }'

## What the charter does once written

- Their domain appears in the classifier's existing-taxonomy block from the next document
- Aliases fold the classifier's inventions onto their canonical path automatically
- Their spec runs **instead of** the general pass for documents in that domain
- Auto-simmer is disabled for the domain, so their spec is never silently replaced.
  `POST /simmer/<domain>` refines it on request, seeded from what they wrote.

## Writing the spec itself

Match the shape of `orchestrator/specs/general_text.md`. It must be **complete and
self-contained** — it is the only spec that will run for that domain, so anything it omits is
not extracted at all. This is the opposite of a simmered domain spec, which is additive.
