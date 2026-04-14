# Orrery Simmer Configuration — For Local Model Agent

*Self-contained reference. Describes exactly how the Orrery uses
simmer-sdk, what the artifacts look like, and what you'd need to
replicate with local models.*

---

## The Two Simmer Phases

The Orrery simmers in two sequential phases. Each is a separate
`refine()` call with different artifacts, criteria, and goals.

### Phase 1: Golden Set (entity taxonomy)

**Goal:** Refine a seed ontology into a domain-appropriate entity
type system with examples and disambiguation rules.

**Seed artifact (iteration 0 input):**
```
Entity types to extract:
- Person — people, speakers, authors, creators
- Organization — companies, groups, teams, brands
- Topic — concepts, ideas, theories, fields, subjects
- Event — happenings, milestones, dates, releases
- Location — places, regions, settings, venues
- Thing — objects, tools, products, materials, artifacts

For each entity found in the text, output:
{"name": "entity name", "type": "EntityType"}

Rules:
- Only extract entities explicitly mentioned in the text
- Normalize names to lowercase
- Do not hallucinate entities not present in the source
```

**refine() call:**
```python
golden_result = await refine(
    artifact=str(seed_path),          # path to seed.md file above
    criteria={
        "coverage": "Captures all entity types present in sample documents",
        "precision": "No hallucinated entities, no noise",
        "taxonomy_quality": "Entity types are meaningful, consistent, and cover the domain",
    },
    primary="coverage",
    iterations=5,
    judge_mode="board",
    judge_panel=[
        {
            "name": "Coverage & Depth",
            "lens": "Focus on whether the spec captures all entity types and important entities present in the sample documents"
        },
        {
            "name": "Precision & Quality",
            "lens": "Focus on whether extracted entities are accurate, well-typed, and free of noise or hallucination"
        },
    ],
    output_dir=golden_dir,
    generator_model="claude-sonnet-4-6",
    judge_model="claude-sonnet-4-6",
    background=f"Sample documents are in {sample_dir}. Read them to understand what entity types exist in this corpus.",
    on_iteration=callback,
    api_provider="bedrock",
    aws_access_key="...",
    aws_secret_key="...",
    aws_region="us-east-1",
)
```

**What the generator produces (after 5 iterations, real output):**
The golden set evolves from the generic 6-type seed into a domain-
specific taxonomy. For a business/tech meeting corpus, it became
8 types: Person, Organization, Product, Technology, Domain, Event,
Location, Money — with disambiguation rules like:

```
Technology vs Domain disambiguation:
- Technology: technical systems you build WITH or ON (frameworks, protocols, APIs)
- Domain: business/industry areas you work IN (sectors, fields, practices)
```

**Typical score trajectory:**
```
golden_set iter 0: 5.0 (seed)
golden_set iter 1: 6.0 (split taxonomy, add Money type)
golden_set iter 2: 6.0 (no improvement)
golden_set iter 3: 7.7 (added Tech/Domain disambiguation rules)
golden_set iter 4: 7.7 (plateau)
golden_set iter 5: 7.7 (abstract-context principle added)
```

### Phase 2: Extraction Spec (prompt for Haiku)

**Goal:** Refine the golden set into a complete extraction prompt
with examples, counter-examples, and boundary rules.

**Seed artifact:** The golden set output from Phase 1 (the taxonomy
with disambiguation rules).

**refine() call:**
```python
spec_result = await refine(
    artifact=golden_result.best_candidate,    # text content, not file path
    criteria={
        "coverage": "When run on sample docs, the spec finds all entities from the golden set",
        "precision": "Zero false positives",
        "format_compliance": "Output is valid JSON with name and type fields",
    },
    primary="coverage",
    iterations=5,
    judge_mode="board",
    judge_panel=[
        {
            "name": "Coverage & Depth",
            "lens": "Focus on whether the spec captures all entity types and important entities present in the sample documents"
        },
        {
            "name": "Precision & Quality",
            "lens": "Focus on whether extracted entities are accurate, well-typed, and free of noise or hallucination"
        },
    ],
    output_dir=spec_dir,
    generator_model="claude-sonnet-4-6",
    judge_model="claude-sonnet-4-6",
    clerk_model="claude-haiku-4-5",
    background=f"This spec will be executed by Haiku. Golden set: {golden_content[:2000]}",
    on_iteration=callback,
    api_provider="bedrock",
    aws_access_key="...",
    aws_secret_key="...",
    aws_region="us-east-1",
)
```

**What the generator produces (real output, ~3400 chars):**
The extraction spec becomes a detailed prompt with:
- Entity type definitions with examples
- Positive extraction examples (8+ showing each type)
- Negative examples ("do NOT extract" rules)
- Disambiguation rules with worked examples
- Format specification (one JSON per line)

Sample from a real spec:
```
Person extraction boundaries:
Extract when a specific person name is mentioned:
- "harper reed", "sarah chen" → Person
Do NOT extract role titles without person names:
- "our CEO mentioned", "the investor said" → do not extract

Organization extraction boundaries:
Extract when a specific organization name is mentioned:
- "betaworks", "google", "sequoia capital" → Organization
Do NOT extract generic organization references:
- "the company", "our firm", "the portfolio company" → do not extract
```

**Typical score trajectory:**
```
extraction_spec iter 0: 4.3 (seed — just the golden set, no examples)
extraction_spec iter 1: 6.3 (added basic examples)
extraction_spec iter 2: 6.3 (no improvement)
extraction_spec iter 3: 7.7 (boundary rules added)
extraction_spec iter 4: 8.3 (Person/Organization boundaries complete)
extraction_spec iter 5: 8.0 (slight regression)
```

---

## Evaluator

**The Orrery does NOT use an evaluator.** The simmer-sdk supports an
`evaluator` parameter for running shell commands against candidates,
but the Orrery relies entirely on the judge board for evaluation.

```python
# This parameter exists in refine() but is NOT used:
evaluator="python evaluate.py --candidate {candidate_path}"
```

The judges evaluate by reading the sample documents (via Read/Grep
tools) and comparing against the criteria. No automated
precision/recall measurement.

**This is a quality gap.** An evaluator that runs extraction against
test chunks and measures precision/recall would significantly improve
the refinement. For local models this could compensate for weaker
judge quality.

---

## Sample Judgment (Real Data)

From the best iteration (extraction_spec iter 4, score 8.3):

**Coverage (8/10, +3 from seed):**
> All 8 entity types present with corpus-specific examples and
> boundaries established for 5 of 8 high-frequency types
> (Person, Organization). Critical gap identified: first-name-only
> extraction accounts for 31% of Person references but is absent
> from spec examples, causing systematic under-extraction.
>
> *Improve:* Add explicit guidance for first-name-only Person
> extraction with examples showing both full name and subsequent
> first-name references in the same document.

**Precision (9/10, +5 from seed):**
> Outstanding improvement with explicit boundaries distinguishing
> named entities from generic references across 5 high-ambiguity
> types. Negative examples comprehensively address false positives
> including role references, possessives, and metadata.
>
> *Improve:* Resolve remaining <10% edge cases by adding explicit
> handling for special characters in names.

**Format Compliance (8/10, +4 from seed):**
> Newline-delimited JSON format clearly specified with 8 complete
> executable examples demonstrating consistent lowercase name
> normalization and proper type field capitalization.
>
> *Improve:* Add special character handling guidance and empty-result
> case specification.

---

## What the Judge Board Does (Internal)

Each iteration, the simmer-sdk:

1. **Generator** (Sonnet) reads the current artifact + the ASI
   (actionable single improvement from last iteration) and produces
   a new candidate.

2. **Two judges** (Sonnet agents with Read/Grep/Glob tools) each:
   - Read the sample documents from disk
   - Evaluate the candidate against the criteria
   - Score each criterion 1-10 with evidence
   - Suggest one improvement

3. **Deliberation** — judges see each other's scores and challenge
   or concede. A synthesis step produces consensus scores.

4. **Reflect** — compares to trajectory, detects regression, picks
   the best candidate to continue from.

The judges use `background` to find the sample documents:
```
background="Sample documents are in /tmp/.../samples. Read them to
understand what entity types exist in this corpus."
```

This means judges actively explore the corpus — they don't just
evaluate the spec in isolation.

---

## Config Summary for Local Model Replacement

| Parameter | Current Value | What It Does |
|---|---|---|
| `generator_model` | claude-sonnet-4-6 | Generates improved specs |
| `judge_model` | claude-sonnet-4-6 | Evaluates specs against criteria |
| `clerk_model` | claude-haiku-4-5 | Used for synthesis/lightweight tasks |
| `judge_mode` | "board" | Two judges deliberate (requires agent runtime) |
| `judge_panel` | 2 entries | Each judge has a "lens" (focus area) |
| `iterations` | 5 | Generate-judge-reflect cycles |
| `primary` | "coverage" | Tiebreaker criterion |
| `background` | Path to sample docs | Judges read these files |
| `api_provider` | "bedrock" | LLM backend |
| `evaluator` | not used | Could add precision/recall measurement |

### What a Local Replacement Needs

1. **Generator** — takes current spec + improvement direction, produces
   better spec. Needs good instruction following and long-context
   understanding (~4000 token spec + ~1000 token improvement direction).

2. **Judge** — evaluates spec against criteria using sample documents.
   In board mode: needs tool use (Read files). In simplified mode:
   documents inlined in prompt (~5000 tokens for 10 docs × 500 tokens each).

3. **Synthesis** — merges two judge opinions into consensus. Simple
   summarization task.

4. **Reflection** — compares scores to trajectory, detects regression.
   This is Python code in simmer-sdk, not an LLM call.

### Minimum Context Windows

- **Generator:** ~8K tokens (spec + ASI + system prompt)
- **Judge (simplified):** ~15K tokens (spec + 10 inlined docs + criteria)
- **Judge (with tools):** ~4K per turn, but 5+ turns of tool use

### Quality Hierarchy

Based on observed runs:
- **Golden set phase** is easier — mostly taxonomy design. 8B models
  could handle this reasonably (the generator just needs to add/modify
  entity type definitions).
- **Extraction spec phase** is harder — needs to produce precise
  boundary rules and counter-examples. Benefits from stronger models.
- **Judging** is the hardest — requires reading documents, comparing
  against criteria, producing quantified scores with evidence.
  Weakest link for local models.
