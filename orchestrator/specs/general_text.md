# Noospheric Orrery: General Entity Extraction Spec

**Purpose:** Catch-all extraction spec for any document entering the Orrery knowledge graph. Produces immediately queryable entities. Domain-specific simmered specs add depth later.

**Design principle:** Extract generously, type conservatively. Better to capture with a generic type than to miss. Normalization and dedup happen downstream.

---

## Entity Types

| Type | What to extract | Examples |
|------|----------------|---------|
| `person` | Named individuals | "Tim Cook", "Duncan Rhodes", "Dr. Sarah Chen" |
| `organization` | Companies, institutions, teams, groups | "Apple", "Games Workshop", "MIT", "2389 Research" |
| `topic` | A field you could take a class in or major in | "machine learning", "organic chemistry", "supply chain management" |
| `concept` | A specific idea, theory, principle, or technique within a field | "reinforcement learning", "Le Chatelier's principle", "value contrast" |
| `technology` | Infrastructure, languages, protocols, standards, frameworks used to build things | "Python", "REST API", "WebSocket", "HIPAA", "Kubernetes" |
| `product` | Named commercial offerings — something you buy, subscribe to, or download | "ChatGPT", "Mephiston Red", "iPhone 15", "Figma" |
| `event` | Named events, conferences, milestones | "WWDC 2025", "Golden Demon", "Series A round" |
| `location` | Places, regions, facilities | "San Francisco", "Building 40", "the Sahara" |
| `document` | Referenced works, papers, books, articles | "Attention Is All You Need", "The Lean Startup" |
| `date_ref` | Specific dates or time periods anchored to a calendar | "Q3 2025", "March 2024", "the 2008 crisis" |
| `metric` | Named measurements, KPIs, benchmarks with numeric values | "95% accuracy", "40% reduction in pipeline time", "$2.3B revenue" |

### Type Decision Tree

When an entity could fit multiple types, apply top-to-bottom. First match wins.

1. **topic vs concept:** Could someone major in it or take a semester-long class titled exactly this? → `topic`. Is it a specific idea, theorem, technique, or principle inside a broader field? → `concept`. Test: "Introduction to [X]" works as a course title → `topic`. "[X] is a key idea in [Y]" where Y is a topic → `concept`.

2. **technology vs product:** Is it a language, protocol, standard, framework, or open infrastructure used to build things? → `technology`. Is it a named commercial offering with a pricing page or app store listing? → `product`. Test: In a `requirements.txt` or `import` statement? → `technology`. Has a pricing page? → `product`. Note: some entities are both (e.g., "AWS" is a product; "S3 API" is a technology). Extract as whichever role the document uses it in.

3. **If still ambiguous:** Use the type whose examples in the table above are most similar. Default to `concept` — it's the broadest non-topic type.

### Custom Type Constraints

Only create a custom `snake_case` type when **both** conditions are met:

1. None of the 11 built-in types fit — you've tried the decision tree and nothing matches.
2. The entity appears 3+ times in the document.

Otherwise use the closest built-in type. Domain-specific specs add richer types later.

---

## Extraction Rules

### What to Extract

An entity qualifies when **at least one** condition is true:

1. **It is a proper noun.** Named people, companies, products, places, events, documents — if the text gives it a capitalized name, extract it.

2. **It is defined or explained in the text.** The author introduces, defines, or teaches it. ("Reinforcement learning is a paradigm where..." → extract as `concept`.)

3. **It is mentioned in 2+ distinct sentences.** Not counting sentences where it only appears inside a prepositional phrase ("about X", "regarding X").

4. **It has a numeric value attached.** Extract as `metric` when a specific number is stated. ("95% accuracy on the test set" → extract. "Good accuracy" → skip.)

### What NOT to Extract

1. **Generic nouns without names.** "The team discussed the problem" — no entities unless the team is identified by name.

2. **Pronouns or unresolved anaphora.** Don't extract "he", "it", "the company." Extract the resolved name only if unambiguous from the same paragraph.

3. **Document structure metadata.** Headers, timestamps, formatting artifacts, page numbers, navigation URLs.

4. **Platform noise.** Subscribe buttons, share links, sponsor mentions — unless the sponsor is discussed substantively (meets condition 1, 2, or 3).

5. **Common English words lacking domain specificity.** "Painting" alone is not an entity. "Oil painting" qualifies only if it meets condition 2 or 3. When in doubt and a condition is met, extract as `topic` or `concept`.

6. **Names that are part of a citation, wherever they appear.** Chunking can split a References
   section from its heading, so don't rely on seeing "References"/"Bibliography" — test each name
   directly instead: if a name (or name list) is followed, within the same sentence or the next
   ~15 words, by any of: a bracketed/numbered citation marker (`[23]`, `(2023)`), a work title, or a
   publication-venue marker ("arXiv", "In Proceedings of...", "Conference on...", a journal name,
   "et al."), it is a citation — skip every name in that citation, not just the first. This applies
   equally to a single citation encountered mid-chunk and to a dense list of them (a references
   section). Test: "Fu, Zhao, and Finn. Mobile ALOHA. CoRL, 2024" → citation, skip all three names,
   even in a chunk with no visible "References" heading.

7. **Non-lead names in a multi-author byline.** When a document opens with a list of authors (e.g. under the title, before an abstract or affiliation line) and that list has 3 or more names, extract only the **first-listed** author as `person`. Do not extract the remaining co-authors — a long byline is not a set of individually graph-worthy entities. (A byline with 1-2 names is short enough that all named authors qualify normally.)

---

## Entity Boundary Guidance

Extract the **most specific named unit** as one entity. Don't split compound names.

- "AWS Lambda" = one entity (`technology`). Do NOT split into "AWS" + "Lambda".
- "New York City" = one entity (`location`). Do NOT split.
- "reinforcement learning from human feedback" = one entity (`concept`). Do NOT split.

Extract the parent entity separately **only** if discussed independently:
- "AWS Lambda runs on AWS infrastructure" → extract both `aws lambda` and `aws`.
- "She used AWS Lambda for the pipeline" → extract only `aws lambda`.

---

## Entity Naming Rules

1. **Canonical form.** Most standard/recognizable version: "Apple" not "Apple Inc." "Tim Cook" not "Timothy Donald Cook."

2. **Lowercase.** All entity names lowercase: "tim cook", "reinforcement learning", "pytorch".

3. **Singularize.** "Machine learning models" → "machine learning model" or "machine learning" depending on context.

4. **Resolve abbreviations when clear.** "ML" → "machine learning". Keep the abbreviation if it IS the standard name ("API" stays as "api").

5. **Dedup before output.** Each entity appears once in the output list.

---

## Worked Example

**Input:**

> Priya Sharma at DeepMind published a paper on contrastive learning in March 2025. The paper showed that contrastive learning with a modified InfoNCE loss achieved 94.2% accuracy on ImageNet, outperforming the previous SimCLR baseline. Sharma's team used PyTorch for all experiments.

**Output:**

```json
{
  "entities": [
    {"name": "priya sharma", "type": "person"},
    {"name": "deepmind", "type": "organization"},
    {"name": "contrastive learning", "type": "concept"},
    {"name": "march 2025", "type": "date_ref"},
    {"name": "infonce loss", "type": "concept"},
    {"name": "94.2% accuracy on imagenet", "type": "metric"},
    {"name": "imagenet", "type": "product"},
    {"name": "simclr", "type": "concept"},
    {"name": "pytorch", "type": "technology"}
  ]
}
```

**Why each was extracted:**

| Entity | Condition | Rationale |
|--------|-----------|-----------|
| priya sharma | #1 proper noun | Named individual |
| deepmind | #1 proper noun | Named organization |
| contrastive learning | #3 mentioned 2+ sentences | Appears in sentences 1 and 2 substantively |
| march 2025 | #1 proper noun | Specific calendar date |
| infonce loss | #2 defined/explained | Described with its result — text explains what it achieved |
| 94.2% accuracy on imagenet | #4 numeric value | Specific benchmark measurement |
| imagenet | #1 proper noun | Named dataset (closest type: product) |
| simclr | #1 proper noun | Named method |
| pytorch | #1 proper noun | Named framework |

**NOT extracted:**
- "paper" — generic noun, no title given
- "team" — "Sharma's team" is descriptive, not a named entity
- "experiments" — common English word, no domain specificity

---

## Output Schema

The extraction produces a flat list of `name + type` pairs:

```json
{
  "entities": [
    {"name": "entity name lowercase", "type": "one of the 11 types above"}
  ]
}
```

That's it. No relationships, no properties, no provenance metadata. The downstream pipeline handles normalization, dedup, co-occurrence, and enrichment.

---

## Execution Notes

- **This spec runs on every document.** Fast and cheap. Use the smallest model that produces acceptable quality.
- **Domain-specific specs supersede this.** Once a domain has its own simmered spec, that handles rich extraction. This general spec provides the rough pass.
- **Err toward recall over precision.** Easier to merge/remove downstream than to discover missed entities. The normalization cascade handles cleanup.
- **Tag output with `extraction_pass: "rough"`** at the pipeline level so domain re-extraction knows what came from the general pass.
