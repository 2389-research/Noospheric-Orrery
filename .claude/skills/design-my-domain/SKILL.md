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

## The two rules

**1. Never ask the user to write an ontology from a blank form.** Experts critique output
fluently and prompts not at all. Show them what the system would actually do, and let them
correct it.

**2. Keep the plumbing offstage.** They care about two things: what came out of their document,
and what you recommend. Everything between those is your problem, not theirs. This section is
written for you; almost none of it is ever spoken.

| Never say | Say instead |
|---|---|
| `taxonomy.json`, reference vocabulary, the classifier | nothing — it is how you decide, not something they hear |
| `business/legal-compliance/contracts` | "I'd file these as contracts" — their word, no path syntax |
| aliases, `domain_merge_map`, normalisation | "do you ever call these something else?" |
| the curl commands, JSON payloads, endpoint names | run them, show the result |
| `run_general`, `specs_applied`, `spec_version`, "the general spec" | "the default setup" |
| simmering, extraction specs, `document_count`, the 20-document threshold | "your version becomes the rule for contracts" |
| `added` / `dropped` / `kept` | New / Dropped / Kept, filled in with their own type names |

The generated rules are the one technical artifact an expert may genuinely want to read. **Offer**
them ("want to see the exact rules?"). Never dump them unasked.

## Process

### 1. Ask what they work on

One question, free text. "Contracts — mostly NDAs and MSAs."

### 2. Find an existing home in the taxonomy — silently

Read `orchestrator/specs/taxonomy.json` and find the closest existing path.
`business/legal-compliance/contracts` already exists.

**Do not narrate this step.** It produces one plain sentence much later, in step 6.

**Prefer reuse.** Reuse is what lets their content merge with everything else in the graph.
Inventing a new top-level region is the failure mode, not the feature. Only invent a path if
nothing in the file is close.

### 3. Ask them to drop in one real document

A real one, not a sample you invent. The whole method depends on them reacting to their own
material.

### 4. Ingest it — for real

    curl -s -X POST "$ORRERY_API/ingest" -F "file=@<their-file>"

This really writes: a document row, chunks, entities, and a `domains` row for whatever path the
classifier picks. That is deliberate, for two reasons — they see genuine graph state, and **the
path it invents is the single most valuable alias you will get**, because you observed it instead
of guessing it. Step 10 cleans up.

Then read the entities back and group them yourself:

    curl -s "$ORRERY_API/documents/<document_id>"

`POST /ingest` returns only a count; the document response carries the entity list
(`canonical_name`, `type`). Group by type, count, and keep 2–3 real names per type.

To them this is one sentence — "let me put this through" — not an account of what gets written.
But do not hide that their document is now in the app: it shows up in the UI, and step 10 asks
their permission to remove it.

### 5. Show them what came out — entities first

Lead with the extraction, because that is what they care about:

- **"Here's what I pulled out of it"** — every type with its count and 2-3 real instances from
  their document

Show the instances. `Date — 47: "January 3, 2024", "the 15th day", "upon signing"` provokes a
useful reaction; `Date — 47` does not.

### 6. Collect their corrections

Two questions, asked separately, in this order — they are already looking at the type list, so
start there:

- **Which of these matter?** What is noise, what is missing entirely? Their answer becomes the
  spec.
- **Is "contracts" what you'd call these?** Then: **do you ever call them something else?**
  Their words — agreements, paperwork, deals — become `aliases`, along with the path the
  classifier actually invented in step 4.

### 7. Validate on a second document

Not optional. The first round always overfits to one sample. Ingest a second document the same
way and show what their corrected type list would have missed.

### 8. Run the worth-it analysis

Compare their corrected type set against what actually came out. Decide with these three buckets;
show them as New / Dropped / Kept, filled in with their own type names.

- **`added`** — types they want that the default never emitted
- **`dropped`** — types it emitted that they rejected
- **`kept`** — the overlap

Then recommend:

- **`added` is non-empty → write the charter.** The default structurally cannot produce those
  types. Waiting does not fix it.
- **`added` empty but `dropped` > half → write the charter.** An authored spec replaces the
  default pass, so the noise genuinely disappears.
- **Otherwise → recommend the default and write nothing.** Say it plainly: "your edits were
  minor, the default already covers this, a custom rule is upkeep you don't need."

**Be willing to reach the third conclusion.** A skill that always recommends its own artifact
is useless as advice.

### 9. Confirm in plain words, then write

Summarise what will happen in their language — their types, their name for the domain — and ask.
**Nothing is written until they say yes.** Then write it without showing the payload:

    curl -s -X POST "$ORRERY_API/charter" -H 'Content-Type: application/json' -d '{
      "domain": "business/legal-compliance/contracts",
      "aliases": ["legal/contracts", "contracts", "legal/agreements"],
      "spec": "# Contract extraction\n..."
    }'

### 10. Clean up the test documents

The documents from steps 4 and 7 were ingested under the default rules, before the charter
existed. Once the charter is written they are stale — leaving them means their entities are the
one part of the graph their own rules never touched.

**Name them before deleting.** This is a hard cascade — entities, chunks, co-occurrence edges,
the document row, and the stored file copy — so say which documents are going, and delete on an
explicit yes. Their original files are untouched; they still have them.

    curl -s -X DELETE "$ORRERY_API/documents/<document_id>"

Then tell them the useful part: anything they add from now on uses their rules.

**If step 8 recommended the default and no charter was written, delete nothing.** Those two
documents were ingested and extracted exactly as they would be in normal use — that is real work,
not test residue. Say so and leave them.

**Known residue:** deleting a document decrements its domain's `document_count` but leaves the
`domains` row, and there is no endpoint that removes one. So the path the classifier invented in
step 4 survives with a count of zero. The alias makes it harmless for classification — later
documents fold onto the canonical path — but it lingers in the classifier's existing-taxonomy
block and on the galaxy map. Do not mention this to the user. Fixing it needs a
`DELETE /domains` endpoint, which is the escalation if it turns out to matter.

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
