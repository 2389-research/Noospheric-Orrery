# Spec Evaluator Design — Empirical Feedback Loop for Extraction Spec Simmering

**Date:** 2026-04-05
**Status:** Approved, ready for implementation

## Problem

Phase 2 of simmering (extraction spec refinement) has no empirical feedback loop. The Sonnet judge panel reasons theoretically about whether a candidate spec would work when run by Haiku — but the spec is never actually tested until batch extraction runs after simmering completes. This means the iterative refinement is based on speculation rather than evidence.

## Solution

Add a standalone evaluator script that runs each iteration's candidate spec against sample documents using Haiku, diffs results against the golden set, writes raw outputs for judges to inspect qualitatively, and prints a quantitative summary. The judges then score based on both empirical metrics and their own read of the raw extraction outputs.

## Architecture

### Evaluation Flow Per Iteration

```
1. Generator (Sonnet) produces candidate spec
2. Evaluator script runs (subprocess):
   a. Load candidate spec
   b. Parse golden set → set of (name, type) tuples
   c. For each sample doc: call Haiku with candidate spec via extract_entities_from_chunk()
   d. Write per-doc raw JSON to eval-{iteration}/
   e. Diff against golden set → precision/recall/F1
   f. Print summary to stdout
3. Judges (Sonnet board) receive:
   a. Evaluator summary in context (automatic via simmer-sdk)
   b. File paths to raw extraction outputs
   c. Explicit instruction to READ the raw outputs, not just trust metrics
4. Judges score qualitatively + quantitatively
```

### Key Insight: Quantitative + Qualitative

The quantitative metrics (precision/recall) get judges in the ballpark, but the real value is judges reading the raw outputs and catching:
- Near-misses where the entity was phrased differently (metric says "miss", reality says "close")
- Technical hits where the type is wrong for the context
- Patterns of systematic failure the numbers alone don't surface
- Extraction quality beyond just matching names (e.g., normalization, specificity)

The judges MUST be instructed to read the raw files, not just the summary.

## New File: `worker/src/jobs/evaluate_spec.py`

Standalone Python script invoked by simmer-sdk's subprocess evaluator mechanism.

### Arguments (command line)

| Arg | Description |
|-----|-------------|
| `--candidate` | Path to candidate spec file (from `{candidate_path}` template) |
| `--samples-dir` | Directory containing sample .txt documents |
| `--golden-set` | Path to the golden set file |
| `--output-dir` | Simmer output directory (from `{output_dir}` template) |
| `--iteration` | Current iteration number (from `{iteration}` template) |

### Behavior

1. **Load inputs**: Read candidate spec text from `--candidate` path. Parse golden set file into `(name, type)` tuples.
2. **Chunk sample docs**: For each sample doc in `--samples-dir`, split into chunks using the same chunking logic the real pipeline uses (fixed-size, ~2000 chars). This ensures the evaluator tests the spec under the same conditions as batch extraction.
3. **Run Haiku**: For each chunk, call `extract_entities_from_chunk()` using `Relay.from_settings()` with `claude-haiku-4-5`. Deduplicate entities per doc (same as `extract_document()`).
4. **Write raw outputs**: Per-doc JSON files to `{output_dir}/eval-{iteration}/{doc_filename}.json`, each containing the full list of extracted entities.
5. **Diff against golden set**: For each doc, compute:
   - Hits: extracted entities matching golden set (case-insensitive name AND type match)
   - Misses: golden set entities not found
   - False positives: extracted entities not in golden set
   - Near-misses: name matches but type differs (flagged separately for judges)
6. **Compute aggregate metrics**: Precision, recall, F1 across all docs.
7. **Print summary to stdout**: Aggregate metrics, per-doc breakdown, file paths to raw outputs.
8. **Fail loudly**: If golden set parsing yields zero entities, exit with non-zero code and clear error message.

### Entry Point

```python
#!/usr/bin/env python
"""Spec evaluator for simmer Phase 2 — runs candidate spec against sample docs with Haiku."""
import argparse, asyncio, json, sys
from pathlib import Path

async def main(args):
    from orrery_relay import Relay
    from src.config import get_settings
    settings = get_settings()
    relay = Relay.from_settings(settings)
    # ... load spec, parse golden set, chunk docs, run Haiku, diff, report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--samples-dir", required=True)
    parser.add_argument("--golden-set", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--iteration", type=int, required=True)
    asyncio.run(main(parser.parse_args()))
```

### Execution

- Uses `asyncio.run()` internally to call async Relay/extractor code
- Instantiates Relay via `Relay.from_settings(get_settings())` — settings come from inherited env vars
- Runs inside the simmer-sdk subprocess mechanism (3600s timeout)
- **Invoked via absolute script path** (not `python -m`) because the subprocess `cwd` is the simmer output directory, not the worker root
- The worker package must be on `PYTHONPATH` for `from src.config import get_settings` to resolve. In Docker this is handled by `pip install -e .` in the worker Dockerfile. For local dev, ensure the worker root is on the path (the evaluator command can prepend `PYTHONPATH=/path/to/worker` if needed)

### Golden Set Parsing

The golden set is a markdown/text file produced by Phase 1. The evaluator needs to extract entity `(name, type)` pairs from it. Since the golden set format may vary, the parser should handle:
- JSON arrays of `{"name": ..., "type": ...}` objects
- Markdown lists like `- EntityName (EntityType)`
- Fallback: treat each line as an entity name if structured parsing fails

### Entity Deduplication vs Golden Set Matching

Two separate operations with intentionally different case behavior:

**Dedup within a doc** (matches real pipeline exactly):
- Key: `(name.lower().strip(), type)` — name is lowercased, type is case-sensitive
- This matches `extract_document()` in `extractor.py` line 52

**Golden set matching** (for computing metrics):
- Case-insensitive on both name and type (both lowercased, stripped)
- A near-miss category for entities where the name matches but type differs (flagged in the summary for judges to review)
- This is intentionally more lenient than dedup — we don't want to penalize the spec for "Person" vs "person" when the golden set and extraction may capitalize differently

## Changes to Existing Files

### `worker/src/jobs/simmer_general.py` — Phase 2

Add `evaluator` parameter to the `refine()` call.

**Important**: `golden_result.best_candidate` is the text content, not a file path. The golden set file is at the known path `{output_dir}/result.md` written by `refine()`. We write it to a stable path before constructing the evaluator command. The evaluator script is invoked via absolute path because the subprocess `cwd` is the simmer output directory, not the worker root.

```python
# Write golden set to a stable path for the evaluator
golden_set_path = specs_dir / "general_golden_set.md"
golden_set_path.write_text(golden_result.best_candidate)

evaluator_script = Path(__file__).resolve().parent / "evaluate_spec.py"

spec_result = await refine(
    artifact=golden_result.best_candidate,
    # ... other params ...
    evaluator=(
        f"python {evaluator_script}"
        f" --candidate {{candidate_path}}"
        f" --samples-dir {sample_dir}"
        f" --golden-set {golden_set_path}"
        f" --output-dir {{output_dir}}"
        f" --iteration {{iteration}}"
    ),
    # ... rest of refine() call ...
)
```

Update `background` to instruct judges about the evaluator outputs:

```python
background=(
    f"This spec will be executed by Haiku to extract entities from documents.\n"
    f"Golden set: {golden_result.best_candidate}\n\n"
    f"IMPORTANT: Each iteration, the evaluator runs the candidate spec against sample docs using Haiku.\n"
    f"Raw extraction results are written to eval-{{iteration}}/ in the output directory.\n"
    f"READ the raw extraction files — don't just trust the quantitative summary.\n"
    f"Look for near-misses, type mismatches, and systematic patterns the metrics miss."
),
```

Update `judge_panel` lenses to emphasize qualitative review:

```python
judge_panel=[
    {
        "name": "Coverage & Depth",
        "lens": "Read the raw Haiku extraction outputs in eval-{iteration}/. "
                "Check: does the spec surface all golden set entities? "
                "Look beyond the precision/recall numbers — are near-misses actually correct? "
                "Are misses due to spec wording or genuine gaps?"
    },
    {
        "name": "Precision & Quality",
        "lens": "Read the raw Haiku extraction outputs in eval-{iteration}/. "
                "Check: are false positives truly wrong, or reasonable entities the golden set missed? "
                "Is the spec causing Haiku to hallucinate, or are extractions grounded in the text?"
    },
],
```

### `worker/src/jobs/simmer_domain.py` — Phase 2

Same pattern as general — add `evaluator` parameter and updated `background`/`judge_panel` to the Phase 2 `refine()` call.

## What Does NOT Change

- **Phase 1 (golden set simmering)**: No evaluator. Judges read sample docs directly to build the taxonomy. This is correct — there's nothing to test the golden set against.
- **simmer-sdk**: Zero changes. Uses the existing `evaluator` parameter and `_run_evaluator()` subprocess mechanism.
- **`orchestrator/src/pipeline/extractor.py`**: Reused as-is by the evaluator script.
- **Iteration storage**: `on_iteration` callback, `simmer_iterations` table, criterion details parsing — all unchanged.
- **Phase 1 judge panels**: Keep existing lenses (they don't need evaluator output).

## Cost Impact

Each Phase 2 iteration runs Haiku on every chunk of every sample doc. With 10 sample docs averaging ~5 chunks each, that's ~50 Haiku calls per iteration. At Haiku pricing (~$0.001/call), this is roughly $0.05 per iteration, or $0.25 per full 5-iteration simmer run. Negligible compared to the Sonnet judge panel costs (~$0.50-1.00 per iteration for 3 judges).

## Evaluator Output Format (stdout)

```
=== Spec Evaluation — Iteration {N} ===

Aggregate: precision={P:.0%}  recall={R:.0%}  F1={F:.0%}
Golden set entities: {total}
Total extracted: {extracted}  |  Hits: {hits}  |  Misses: {misses}  |  False positives: {fps}

--- Per-doc breakdown ---
{doc_id}.txt: extracted={n}, hits={h}, misses={m}, false_pos={fp}
  Near-misses (name match, type differs): {list}
  Missed: {list of golden entities not found}
{...repeat for each doc...}

--- Raw outputs ---
Read the full extraction results at: {output_dir}/eval-{iteration}/
Files: {list of .json filenames}
```

## File Layout During Simmering

```
specs/
  general_spec/                    # Phase 2 output dir
    iteration-0-candidate.md
    iteration-0-judgment.md
    iteration-1-candidate.md
    iteration-1-judgment.md
    eval-0/                        # NEW: evaluator outputs
      {doc_id}.json                # Raw Haiku extraction per doc
    eval-1/
      {doc_id}.json
    ...
```
