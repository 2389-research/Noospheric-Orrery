---
name: design-your-orrery
description: Use when a Noospheric Orrery user wants to design a custom domain extraction spec for their own content (e.g. "I want an Orrery for legal contracts / recipes / support tickets") — brainstorms the domain's entity types and extraction rules, using the research_paper section-spec work as a worked example, and writes a spec doc the user can hand to a simmer job.
---

# Design Your Orrery

Noospheric Orrery already classifies any document into a domain and extracts entities using a
**general spec** (`orchestrator/specs/general_text.md`). That's built in — every document already
gets people, organizations, topics, concepts, technologies, metrics, and date references for free.

This skill is for the next step: when a domain's content has structure the general spec can't see
(academic papers have abstracts/methods/results; legal contracts have clauses/parties/obligations;
support tickets have symptoms/resolutions/products), you write a **domain-specific spec** that runs
*additively* alongside the general one and captures only what's specific to that domain.

## When to use this

The user says something like "I want to build my own version of this for X" — X being some category
of document they work with, distinct from the generic news/business/research content the built-in
tutorial and taxonomy already cover.

## How specs actually work here (read this before designing anything)

- **Domain specs are database rows, not files** — `store.specs.get_for_domain(domain_path)`,
  version-tracked, applied during ingest (`orchestrator/src/routes/ingest.py`, "4. Cascade through
  domain specs"). They get created by running a **simmer job**
  (`POST /simmer/{domain_path}` — see `worker/src/jobs/simmer_domain.py`), not by hand-writing a
  file and expecting it to be picked up automatically.
- **The exception**: `orchestrator/specs/research_paper/` on the `feature/research-paper-section-spec`
  branch is a hand-authored, per-section variant of this same idea (one small `.md` file per paper
  section — abstract, method, experiments, etc. — plus a `shared.md` with the entity-type table and
  decision tree, and a `default.md` fallback). It's the worked example this skill leans on, but it's
  a special case (section-stratified extraction, not the normal path) — most custom domains should
  go through the simmer job, not a hand-authored file tree.
- **A domain spec is additive, not a replacement.** It must NOT re-extract types the general spec
  already gets (person, organization, topic, concept, technology, metric, date_ref). It exists only
  to name the entity types specific to this domain.
- **Domain cascade**: specs apply deepest-ancestor-first up a domain path
  (`business/product_development/strategy` gets the `strategy` spec, then `product_development`,
  then `business`) — so a new domain spec should know where in the taxonomy it's meant to sit.

## The worked example: `research_paper`

Read `orchestrator/specs/research_paper/shared.md` (on `feature/research-paper-section-spec` —
`git show feature/research-paper-section-spec:orchestrator/specs/research_paper/shared.md` if
you're not on that branch) end to end before designing a new domain. It demonstrates the pattern to
copy:

1. **A short "why additive" preamble** stating explicitly which general-spec types NOT to
   re-extract, and why (person/organization scoping lives in the general spec, not here, because
   it's a universal need, not domain-specific).
2. **An entity type table**: `Type | What to extract | Examples` — 4-6 new types max. For
   `research_paper`: `model`, `method`, `task`, `apparatus`, `dataset`, `platform`.
3. **A type decision tree** for the genuinely ambiguous boundaries (model vs. method, task vs.
   topic) — phrased as a testable question ("Does it have its own name and produce end-to-end
   outputs evaluated as a whole? → model. Is it a sub-technique used inside another model's
   training/inference? → method."), not a vague description. This is the part that actually
   prevents inconsistent extraction; don't skip it.

## Process for a new domain

1. **Ask the user what content this domain covers and get 2-3 real (or representative) examples.**
   You cannot design entity types from a one-line description — you need to see what's actually in
   the documents.
2. **Identify what the general spec already covers** for this content (usually: people, orgs,
   dates, named concepts) and explicitly exclude those from the new spec.
3. **Name 3-6 new entity types** specific to this domain, each with a one-line "what to extract"
   description and 2-4 concrete examples pulled from the user's real content — not invented
   placeholders.
4. **Write the decision tree** for any pair of types that could plausibly be confused for each
   other. If there's no ambiguity, skip this — don't invent a decision tree nobody needs.
5. **Decide where this domain sits in the taxonomy** (`orchestrator/specs/taxonomy.json` —
   region/category/topic) so the cascade applies at the right level, or confirm it should be a new
   top-level domain the classifier will invent.
6. **Write the spec as markdown** in the same shape as `research_paper/shared.md` (preamble, type
   table, decision tree) and hand it to the user as the body to paste into a simmer job — either via
   `POST /simmer/{domain_path}` once they have enough documents in that domain (the normal path), or
   as a per-section file tree like `research_paper/` only if the domain genuinely has strong
   positional structure (sections that always appear in the same order with predictably different
   content, like a paper's abstract vs. its experiments).
7. **Flag the general-spec threshold**: domain simmering only triggers automatically once
   `domain.document_count >= domain_spec_threshold` (config, default in `config.py`). For an early
   design/test pass, the user can trigger it manually rather than waiting to hit that count.

## What NOT to do

- Don't re-derive person/organization/date extraction — that's the general spec's job.
- Don't propose a giant type list. 3-6 new types is the range that's actually held to consistently;
  `research_paper` has 5.
- Don't skip asking for real example documents — a spec designed from imagination produces vague
  "what to extract" descriptions that extract inconsistently in practice.
- Don't assume file-tree specs like `research_paper/` are the normal path — they're a special case
  for content with strong positional/section structure. Most domains should go through a simmer job
  against a single spec, the way every other domain in this product works.
