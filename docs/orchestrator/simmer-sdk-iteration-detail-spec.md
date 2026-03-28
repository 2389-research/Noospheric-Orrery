# Simmer SDK — Per-Criterion Iteration Detail

**Date:** 2026-03-27
**Purpose:** Expose per-criterion judge reasoning in the `on_iteration` callback
**Requester:** Noospheric Orrery UI — needs structured judge output for the simmer progress visualization

## Current State

The `IterationRecord` passed to `on_iteration` has:
```python
IterationRecord.scores: dict[str, int]     # {"coverage": 8, "precision": 6}
IterationRecord.key_change: str            # "Split Thing into Product+Technology"
IterationRecord.asi: str                   # single text block summarizing everything
```

The raw judge output (visible in older runs as `iteration-N-judgment.md` files) has per-criterion structure:
```markdown
## Criterion 1: Concept Coverage
Score: 8/10 (seed: 7/10)
Evidence: "The v1 extractor is genuinely more thorough..."
What would make it better: "missing dragon model entry..."
```

This per-criterion structure exists inside the judge flow but gets collapsed into the single `asi` string before reaching `IterationRecord`.

## What We Need

Add a `criterion_details` field to `IterationRecord`:

```python
@dataclass
class CriterionDetail:
    criterion: str        # "coverage", "precision", etc.
    score: int            # 0-10
    seed_score: int       # score from iteration 0 for this criterion
    evidence: str         # what the judge observed
    improve: str          # what would make it better (forward-looking)

@dataclass
class IterationRecord:
    iteration: int
    scores: dict[str, int]           # existing — keep for backward compat
    key_change: str                  # existing
    asi: str                         # existing — keep as summary fallback
    regressed: bool                  # existing
    judge_mode: str                  # existing
    criterion_details: list[CriterionDetail] = []  # NEW
```

## Where the Data Comes From

The judge already produces per-criterion reasoning. In `judge.py` and `judge_board.py`, the judge prompt asks for per-criterion scores with evidence. The synthesis step in board mode merges these into a single ASI.

The change is to **also preserve the per-criterion breakdown** alongside the ASI, not replace it. The ASI is still useful as a header-level summary.

For single-judge mode: parse the judge output into per-criterion blocks.
For board mode: the synthesis step already has per-criterion scores — preserve the per-criterion evidence from the synthesized output.

## Seed Score Tracking

The `seed_score` field requires knowing iteration 0's scores. The trajectory already tracks this — `trajectory[0].scores` has the seed scores. When building `CriterionDetail`, look up the seed score for each criterion from the trajectory.

## How the Orrery Will Use It

The `on_iteration` callback stores criterion_details in the DB:

```python
# In the callback
for detail in record.criterion_details:
    conn.execute(
        "INSERT INTO simmer_criterion_details (iteration_id, criterion, score, seed_score, evidence, improve) VALUES (?, ?, ?, ?, ?, ?)",
        (iteration_id, detail.criterion, detail.score, detail.seed_score, detail.evidence, detail.improve),
    )
```

The UI renders each criterion as a collapsible card:
```
┌─ Coverage ────────────────── 8/10 (+2 from seed) ─┐
│ Evidence: "v1 extractor more thorough than seed..."│
│ Improve:  "missing dragon model entry"             │
└────────────────────────────────────────────────────┘
```

The `improve` field from iteration N connects to `key_change` of iteration N+1 — showing the judge's feedback → generator's response loop.

## Scope

- **In scope:** Add `criterion_details` to `IterationRecord`, populate from judge output
- **In scope:** Track seed scores for delta display
- **In scope:** Both single-judge and board mode
- **Out of scope:** Changing the judge prompt or scoring rubric
- **Backward compatible:** `criterion_details` defaults to empty list, existing code unaffected

## Testing

- Existing tests pass (field is optional with default)
- New test: run a 2-iteration refine, verify `criterion_details` is populated on iteration 1+
- Verify `seed_score` matches iteration 0 scores
- Verify both single and board mode produce details
