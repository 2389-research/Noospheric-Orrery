# Section-Stratified Research Paper Extraction Spec

**Date:** 2026-07-29
**Status:** Approved for planning

## Problem

`orchestrator/specs/domain_research_paper.md` is a single flat rule set applied uniformly to
every 2000-char chunk of a research paper, regardless of where in the paper that chunk falls.
Chunking (`chunker.py`) is pure fixed-size windowing with no notion of paper structure.

This is a problem specifically because extraction runs on a **weaker model**
(`EXTRACTION_MODEL`). Different sections of a paper have very different extraction failure
modes:

- **Introduction** — loose prose, vague capability claims, restates the hero model/task
  informally. Weak models over-extract generic capability phrases as tasks.
- **Related Work** — citation-dense. Weak models over-extract cited baseline model names that
  should be skipped per the citation rule.
- **Method** — dense named-technique text; this is where `method` boundary-drawing (model vs.
  method) matters most.
- **Experiments/Results** — highest density of `model`/`task`/`metric`-worthy content (baseline
  comparisons, ablations, named tasks with outcomes).
- **Conclusion** — mostly restates already-extracted entities; risk of low-value duplicate
  self-reference extraction.

A single spec asks a weak model to hold all of these distinctions in its head at once for every
chunk. The fix is to give each chunk only the rules relevant to its section.

## Design

### 1. Section detection — `orchestrator/src/pipeline/section_splitter.py`

New pure function, hybrid heuristic + LLM fallback:

- **Heuristic pass:** regex over lines for standard academic heading patterns — markdown
  headings, numbered headings (`1. Introduction`, `IV. EXPERIMENTS`), and short standalone lines
  matching a keyword set (`introduction`, `related work`, `background`, `method`, `approach`,
  `experiments`, `results`, `discussion`, `conclusion`, `abstract`, `limitations`). Produces a
  list of heading matches with character offsets.
- **Fallback:** any span between two heading matches (or before the first) that is
  disproportionately long relative to the median detected section length, or where no heading was
  found at all, is labeled `unclassified` and gets a single LLM classification call per span (not
  per chunk): "which of [introduction, related_work, method, experiments, conclusion, abstract,
  other] does this text belong to?"
- **Output:** `list[{"section": str, "start": int, "end": int}]` covering the full document with
  no gaps.

### 2. Section-aware chunking

`chunk_document` keeps its existing 2000-char/200-overlap windowing logic unchanged. Chunking
runs **per section span** instead of over the whole document, so no chunk straddles a section
boundary. Each chunk dict gains a `"section"` key. This requires:
- A new orchestrator-side wrapper (e.g. `chunk_sections(text) -> list[dict]`) that calls
  `section_splitter` then `chunk_document` per span and stitches chunk_index/offset back together
  across the whole document.
- A `section` column on the `chunks` table (migration) so the domain-cascade extraction pass can
  look up each chunk's section later without re-splitting.

### 3. Spec files — `orchestrator/specs/research_paper/`

Replace the single `domain_research_paper.md` with a directory:

```
orchestrator/specs/research_paper/
  shared.md          — type table, decision tree, custom-type constraints, naming rules
  default.md          — fallback spec for "unclassified"-section chunks (~today's spec body)
  introduction.md
  related_work.md
  method.md
  experiments.md
  conclusion.md
  abstract.md
```

`shared.md` holds everything that doesn't vary by section (today's existing content mostly
survives here unchanged). Each section file is short and additive on top of `shared.md`, focused
on that section's specific weak-model failure mode (see Problem section above) — e.g.
`related_work.md` reiterates and tightens the citation-skip rule; `introduction.md` tightens the
"vague capability claim" rejection rule; `experiments.md` leans toward recall on
model/task/metric density.

### 4. Extraction wiring

- `extract_document` (`extractor.py`) signature changes from `spec: str` to
  `section_specs: dict[str, str]` (section name → full prompt text, pre-composed as
  `shared.md + section.md`). Per chunk, it looks up `chunk["section"]`, falling back to
  `section_specs["default"]` if the section key is missing/unrecognized.
- `ingest.py`'s domain-cascade loop: when the resolved domain spec is the `research_paper`
  built-in (no simmered override yet), load the whole `research_paper/` directory and build the
  `section_specs` dict once per ingest call, rather than reading one `.md` file.
- Simmered domain specs (the existing per-domain simmer loop) are unaffected for now — this
  section-stratification applies to the built-in `research_paper` spec directory only. Simmering
  section-specific sub-specs is out of scope for this design (noted as future work).

### 5. Testing script — `orchestrator/scripts/test_section_spec.py`

Standalone CLI script, no server/DB dependency, calls `Relay` directly against
`settings.extraction_model` (the actual weak model in use). Test fixtures come from the raw PDFs
in `pi0/papers/` (andersonVLN2018.pdf, kimOpenVLA2024.pdf, linVILA2024.pdf, wangCLASH2026.pdf,
etc.) — real, un-pre-processed papers, not the already-plain-text `pi0/*.txt` files — run through
the repo's existing `extract_text_from_pdf` (`orchestrator/src/pipeline/file_extractor.py`) so the
test path matches what a real PDF upload actually produces (page-break artifacts, column-merge
noise, etc. included):

```bash
python -m scripts.test_section_spec --paper pi0/papers/kimOpenVLA2024.pdf --section introduction
python -m scripts.test_section_spec --paper pi0/papers/wangCLASH2026.pdf --all-sections
```

Behavior:
1. Read the PDF file's bytes and run them through `extract_text_from_pdf` to get raw text (same
   function the real ingest path uses — no separately-maintained .txt fixtures to go stale).
2. Run `section_splitter` on that extracted text to get section spans.
3. For the requested section (or all sections), extract just that span's text, chunk it with
   `chunk_document`, and run `extract_entities_from_chunk` against `shared.md + <section>.md`.
4. Print a raw entity dump grouped by chunk index (entity name + type), plus the section
   boundaries detected (start/end char offsets) so mis-detected sections are visible.

No expected-answer scoring/diffing — this is a fast manual-iteration loop: run it, eyeball the
output, edit the section's `.md` file, rerun. Automated golden-set scoring is out of scope (the
existing simmer machinery already does that for whole-document specs; wiring section-level specs
into simmer is future work, not this design).

## Out of scope

- Simmering per-section sub-specs through the existing `simmer_core.py` loop.
- Changing `general_text.md` or the general extraction pass.
- Any frontend/API surface for this — it's a spec-authoring tool for you, not a product feature.
- Automated precision/recall grading of section-level extraction (raw dump only, per your call).

## Testing

- New `section_splitter.py` gets unit tests: known heading patterns detected correctly, span
  coverage has no gaps/overlaps, fallback classification triggers when no headings exist.
- Existing `chunker.py` tests unaffected — its core function signature/behavior doesn't change,
  only how it's invoked (per-span vs whole-document).
- `test_section_spec.py` is validated manually against the PDFs in `pi0/papers/` (real,
  unprocessed papers run through `extract_text_from_pdf`) as part of building it — that's the
  whole point of the tool.
