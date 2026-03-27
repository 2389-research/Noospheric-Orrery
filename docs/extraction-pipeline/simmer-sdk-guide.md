# Simmer SDK Guide — For the Extraction Pipeline

**Date:** 2026-03-27
**Status:** Reference documentation for pipeline developers
**Source:** `~/Documents/GitHub/simmer-sdk/`

The simmer-sdk is the engine that drives Phases 1 and 2 of the extraction pipeline. This guide covers how to invoke it, configure it for different extraction tasks, and integrate it into automated pipelines.

---

## What Simmer Does

Simmer takes an artifact and iteratively refines it against criteria you define. Each iteration: a generator improves the artifact, an optional evaluator runs hard metrics, a judge (or judge board) scores against criteria, and a reflect step tracks progress. After N iterations, you get the best version.

In this pipeline, simmer runs twice:
1. **Phase 1 — Gold standard simmering:** The artifact is an annotated eval set. Criteria measure annotation quality.
2. **Phase 2 — Extraction spec simmering:** The artifact is a prompt/spec. The evaluator runs the spec against the gold standard via Haiku. Criteria measure extraction quality (recall, precision, type accuracy).

---

## Installation

```bash
# From the simmer-sdk directory
cd ~/Documents/GitHub/simmer-sdk
uv sync --all-extras

# Or install as a dependency in your project
uv add --path ~/Documents/GitHub/simmer-sdk
```

Requires `ANTHROPIC_API_KEY` set in your environment.

---

## Basic Invocation

```python
import anyio
from pathlib import Path
from simmer_sdk import refine

async def main():
    result = await refine(
        artifact="...",           # what to refine
        criteria={...},           # what "better" means
        iterations=3,             # how many generate-judge cycles
        output_dir=Path("..."),   # where to write iteration files
    )
    print(result.best_candidate)

anyio.run(main)
```

---

## Configuration Reference

Every parameter maps to the simmer skill's setup brief:

### Required

| Parameter | Type | Description |
|-----------|------|-------------|
| `artifact` | `str \| Path` | The thing to refine. Text content, file path, directory path, or description (seedless mode). |
| `criteria` | `dict[str, str]` | Scoring rubric. Keys are criterion names, values describe what 10/10 looks like. Max 3 recommended. |

### Mode & Artifact Type

| Parameter | Default | Options | Description |
|-----------|---------|---------|-------------|
| `mode` | `"auto"` | `"auto"`, `"seedless"`, `"from-file"`, `"from-paste"`, `"from-workspace"` | How the initial artifact is provided. Auto-detected from artifact content. |
| `output_dir` | `"docs/simmer"` | Any path | Where iteration candidate files, trajectory.md, and result.md are written. |

- **seedless**: artifact is a description; generator creates the first candidate
- **from-file**: artifact is a file path; contents are the seed
- **from-paste**: artifact is text content; it's the seed directly
- **from-workspace**: artifact is a directory; generator edits files in place, tracked via git commits

### Evaluation

| Parameter | Default | Description |
|-----------|---------|-------------|
| `evaluator` | `None` | Shell command run after each generator step. Stdout/stderr passed to judge as evidence. |
| `primary` | `None` | Criterion name for best-so-far comparison. If set, this criterion trumps composite for ranking. |

**Evaluator template variables:**

| Variable | Replaced with |
|----------|--------------|
| `{candidate_path}` | Absolute path to the current iteration's candidate file |
| `{output_dir}` | The simmer output directory |
| `{iteration}` | Current iteration number |

Example evaluator commands:
```python
# Run extraction spec against gold standard
evaluator="bash sdk_eval_haiku.sh {candidate_path} {output_dir}/eval_v{iteration}"

# Simple word count check
evaluator="wc -w {candidate_path}"

# Python test suite
evaluator="python eval_scorer.py --spec {candidate_path} --gold gold_standard/"
```

### Judge Configuration

| Parameter | Default | Options | Description |
|-----------|---------|---------|-------------|
| `judge_mode` | `"auto"` | `"auto"`, `"single"`, `"board"` | Single judge or 3-judge board with deliberation. Auto-selects based on complexity. |
| `judge_panel` | `None` | `list[dict]` | Custom judge definitions. Each dict has `name` and `lens` keys. Overrides auto-composition. |

**Auto-selection rules:**
- text/creative, <=2 criteria → single judge
- text/creative, 3+ criteria → board
- code/testable or pipeline/engineering → board

**Board mode:** 3 judges composed for the specific problem (or custom panel), score independently, deliberate one round (see each other's scores, not ASI), then a synthesis step distills one focused ASI. More expensive but catches blind spots.

### Model Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `generator_model` | `"claude-sonnet-4-6"` | Model for the generator subagent |
| `judge_model` | `"claude-sonnet-4-6"` | Model for judge subagents and board synthesis |
| `clerk_model` | `"claude-haiku-4-5"` | Model for board composition and reflect step |

Every LLM call is independently configurable. For cost-sensitive pipelines, use haiku for everything. For quality-sensitive work, sonnet across the board.

### AWS Bedrock

The Noospheric Orrery uses Bedrock. Pass credentials via `refine()`:

```python
result = await refine(
    ...,
    api_provider="bedrock",
    aws_access_key="AKIA...",
    aws_secret_key="...",
    aws_region="us-east-1",
    generator_model="claude-sonnet-4-5",
    judge_model="claude-sonnet-4-5",
    clerk_model="claude-haiku-4-5",
)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `api_provider` | `"anthropic"` | `"anthropic"` or `"bedrock"` |
| `aws_access_key` | `None` | AWS IAM access key ID |
| `aws_secret_key` | `None` | AWS IAM secret access key |
| `aws_region` | `None` | AWS region (e.g., `"us-east-1"`) |

Model IDs are auto-mapped to Bedrock format. `claude-sonnet-4-5` becomes `us.anthropic.claude-sonnet-4-5-20250929-v1:0`. You can also pass Bedrock IDs directly.

**Note:** Sonnet 4.6 and Opus 4.6 are not yet available on Bedrock. Use `claude-sonnet-4-5` and `claude-haiku-4-5` for now. The mapping will auto-fallback to 4.5 if you pass 4.6 model names.

### Context & Constraints

| Parameter | Default | Description |
|-----------|---------|-------------|
| `background` | `None` | Persistent constraints, available resources, domain knowledge. Passed to generator and judges every iteration. |
| `output_contract` | `None` | Valid output format description. Judges check for contract violations. |
| `validation_command` | `None` | Quick check command for workspace mode (cheaper than full evaluator). |
| `search_space` | `None` | What's in scope to explore (models, topologies, parameters). |

### Callbacks

```python
async def on_iteration(record, trajectory, trajectory_table):
    """Called after each iteration."""
    print(trajectory_table)  # formatted markdown trajectory

async def on_plateau(trajectory):
    """Called when 3 iterations without improvement.
    Return True to upgrade from single judge to board."""
    return True
```

---

## Pipeline Integration Patterns

### Phase 1: Gold Standard Simmering

```python
result = await refine(
    artifact=(
        "Annotate 20 document segments with domain-specific entities. "
        "Discover the entity type taxonomy, annotation rules, and edge cases. "
        "Output: JSON entities per segment with name, type, and rationale."
    ),
    criteria={
        "coverage": "captures all significant domain entities from the content",
        "type_quality": "entity types are specific, non-overlapping, and meaningful for this domain",
        "annotation_rules": "rules are concrete and testable, not vague guidelines",
    },
    primary="coverage",
    iterations=4,
    mode="seedless",
    judge_mode="board",
    background=(
        "Domain: miniature painting tutorials (YouTube transcripts). "
        "Parent types already exist: paint, color, tool, model. "
        "This spec should discover subdomain-specific types that complement the parent."
    ),
    output_dir=Path("sdk_gold_simmer"),
    # Bedrock config
    api_provider="bedrock",
    aws_access_key=os.environ["AWS_ACCESS_KEY"],
    aws_secret_key=os.environ["AWS_SECRET_KEY"],
    aws_region=os.environ.get("AWS_REGION", "us-east-1"),
    generator_model="claude-sonnet-4-5",
    judge_model="claude-sonnet-4-5",
    clerk_model="claude-haiku-4-5",
)
```

### Phase 2: Extraction Spec Simmering (with evaluator)

```python
result = await refine(
    artifact="path/to/initial_spec.md",    # or seedless
    criteria={
        "recall": "extracts all gold standard entities — 10/10 means zero misses",
        "precision": "no false positives or hallucinated entities — 10/10 means zero noise",
        "type_accuracy": "entity types match gold standard — 10/10 means every type correct",
    },
    primary="recall",
    evaluator="bash sdk_eval_haiku.sh {candidate_path} {output_dir}/eval_v{iteration}",
    iterations=5,
    mode="from-file",      # or "seedless" if no initial spec
    judge_mode="board",
    background=(
        "Execution model: Haiku 4.5 via API. "
        "Domain: miniature painting. "
        "Gold standard: 156 entities across 20 segments, 14 types. "
        "The spec must be executable by Haiku — keep instructions concrete."
    ),
    output_dir=Path("sdk_spec_simmer_haiku"),
    # Bedrock config
    api_provider="bedrock",
    aws_access_key=os.environ["AWS_ACCESS_KEY"],
    aws_secret_key=os.environ["AWS_SECRET_KEY"],
    aws_region=os.environ.get("AWS_REGION", "us-east-1"),
    generator_model="claude-sonnet-4-5",
    judge_model="claude-sonnet-4-5",
    clerk_model="claude-haiku-4-5",
)
```

### Evaluator Script Pattern

The evaluator is a shell command. For extraction spec simmering, the pattern is:

```bash
#!/bin/bash
# sdk_eval_haiku.sh — evaluator for simmer-sdk
# Usage: sdk_eval_haiku.sh <spec_path> <output_dir>

SPEC="$1"
OUTPUT_DIR="$2"

# Run extraction with the spec
python eval_runner_haiku.py --spec "$SPEC" --output "$OUTPUT_DIR"

# Score against gold standard
python eval_scorer.py --extracted "$OUTPUT_DIR" --gold sdk_gold_standard/
```

The scorer's stdout (recall, precision, type accuracy, per-segment breakdowns) is passed directly to the judge board as `EVALUATOR OUTPUT`. The judges interpret these metrics alongside the criteria to produce scores and ASI.

---

## Output

### SimmerResult

```python
result.best_candidate   # str — the best artifact text
result.best_iteration   # int — which iteration was best
result.best_scores      # dict — per-criterion scores
result.composite        # float — best composite score
result.trajectory       # list[IterationRecord] — full history
result.stable_wins      # list[str] — what's been working
result.not_working      # list[str] — what's been tried and failed
result.output_dir       # Path — where files were written
```

### Output Directory

```
{output_dir}/
  iteration-0-candidate.md     # seed (or first generation)
  iteration-1-candidate.md     # each improved candidate
  ...
  trajectory.md                # running score table (updated each iteration)
  result.md                    # copy of best candidate
```

For workspace mode, iterations are tracked via git commits instead of separate files.

---

## Context Discipline

This matters for understanding the quality of simmer's output. The skill enforces strict information boundaries:

| Role | Receives | Does NOT receive |
|------|----------|------------------|
| Generator | Current candidate, criteria, ASI, background | Scores, previous candidates, evaluator output |
| Judge (text/creative) | Current candidate, criteria, seed reference | Intermediate scores, previous ASI, trajectory |
| Judge (code/pipeline) | Above + evaluator output, previous ASI, iteration history | Full candidate history |
| Reflect | Full judge output, trajectory.md | Candidate content |

The generator works from ASI (specific improvement direction), not from scores. The judge scores fresh against criteria and the seed as calibration, not against previous scores. This prevents anchoring bias and score inflation.

---

## Key Behaviors

### Regression Detection
If an iteration scores worse than the best so far, the next generator receives the best candidate (not the regressed one) plus a note explaining the rollback. For workspace mode, this is a selective git checkout.

### Plateau Detection
If the best score hasn't improved for 3 consecutive iterations and you're using a single judge, the `on_plateau` callback fires. Return `True` to upgrade to a board for deeper analysis.

### Stable Wins
The reflect step tracks which changes held across iterations (WORKING) and which caused regressions (NOT WORKING). This prevents the generator from removing load-bearing elements or retrying failed approaches.

### Investigation-First Judges
Judges have tool access (Read, Grep, Glob). They read the candidate file, evaluator script, and prior candidates before scoring. For extraction pipelines, this means the judge reads the evaluator script to understand HOW it scores (fuzzy matching? exact match? case-sensitive?) rather than discovering this through trial and error.

---

## Troubleshooting

### Evaluator not running
Check that `{candidate_path}` is in your evaluator command string. The SDK replaces it with the absolute path to the current candidate file. If your evaluator command has a literal path, it won't update between iterations.

### Scores missing from trajectory
The reflect agent writes trajectory.md via the Write tool. If scores are missing, the reflect agent may not have extracted them from the judge output. Check `trajectory.md` directly — if it exists but has `-` for scores, the judge output format may have diverged.

### Word count growing each iteration
Add a word count evaluator: `evaluator="wc -w {candidate_path}"`. The judges will factor word count into their scoring. For hard constraints, put the target in the criteria description: "10/10 means complete coverage in under 500 words."

### Board composition seems generic
The board composes 3 problem-specific judges at the start of the run. If the judges seem generic (Analyst/Pragmatist/Critic), the composition prompt may not have enough context. Add more detail to `background` about the domain and what makes good work in this space.

---

## Simmer SDK Source

```
~/Documents/GitHub/simmer-sdk/
├── src/simmer_sdk/
│   ├── refine.py              # main loop orchestrator
│   ├── generator.py           # generator subagent dispatch
│   ├── judge.py               # single judge dispatch
│   ├── judge_board.py         # board composition + deliberation + synthesis
│   ├── reflect.py             # LLM-based reflect (trajectory, regression, stable wins)
│   ├── prompts.py             # prompt builders (load actual skill files)
│   ├── primitives.py          # judge primitive library
│   ├── setup.py               # problem classification, judge mode selection
│   ├── types.py               # data classes
│   └── skill_reference/       # actual Claude Code skill .md files used as prompts
├── tests/
│   ├── reference/             # recorded experiment results for comparison
│   └── test_*.py              # unit + integration tests
└── docs/
    └── spec.md                # original API specification
```
