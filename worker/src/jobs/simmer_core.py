# ABOUTME: Reusable simmer framework — the generate→evaluate→judge→reflect loop, decomposed.
# ABOUTME: Non-agentic relay judge (reuses simmer-sdk's parser) + loop + iteration recording.
#
# This is the canonical simmer process (simmer-sdk/docs/spec.md) with the agentic execution
# swapped for bounded relay calls so local models (gemma4) don't stall:
#   - Generator: a decomposed bounded call (the caller supplies generate_fn) — gets candidate + ASI.
#   - Evaluator: optional deterministic measurement (caller supplies evaluator_fn) — no LLM.
#   - Judge: ONE non-agentic relay.complete call (evidence pre-loaded, no tools) → scores + ASI.
#            Reuses simmer-sdk's proven parse_judge_output so the output format is identical to
#            the agentic judge; runs through orrery-relay so think:false applies (no reasoning bug).
#   - Reflect: best-so-far + regression flag (Python).
# Context discipline (spec.md): the generator receives candidate + ASI + background, NEVER scores
# or evaluator output; the judge receives candidate + evidence (+ evaluator output), calibrated to seed.

import json
import re
import uuid

from orrery_relay import Relay
from simmer_sdk.judge import parse_judge_output

from ..db import get_connection


JUDGE_PROMPT = """You are evaluating a candidate artifact against the corpus it was built from and a set of criteria. Be precise and critical. Respond directly — do NOT use extended thinking, do NOT use tools.

CRITERIA:
{criteria_block}

CANDIDATE (iteration {iteration}):
{candidate}

CORPUS EVIDENCE — what is actually present in the source material. Judge ONLY against this; do not assume anything not shown here:
{evidence}
{evaluator_block}
Score each criterion from 0 to 10 based strictly on the evidence above, then give the single
highest-leverage improvement. Output EXACTLY this format and nothing else:

ITERATION {iteration} SCORES:
{score_lines_hint}
COMPOSITE: [average of the scores]/10

ASI (highest-leverage direction):
[the single most impactful, specific, actionable change that would most improve the candidate's weakest criterion]"""


async def relay_judge(candidate: str, evidence: str, criteria: dict, settings,
                      iteration: int = 0, evaluator_output: str | None = None):
    """Non-agentic judge: one relay.complete call, evidence pre-loaded, no tools.

    Returns a simmer-sdk JudgeOutput (scores + asi + per-criterion reasoning), parsed with
    simmer-sdk's own parser so it's format-identical to the agentic judge.
    """
    relay = Relay.from_settings(settings)
    criteria_block = "\n".join(f"- {k}: {v}" for k, v in criteria.items())
    score_lines_hint = "\n".join(f"  {k}: [N]/10 — [reasoning] — [what would improve it]" for k in criteria)
    evaluator_block = (f"\nEVALUATOR RESULTS (deterministic measurements on this candidate):\n{evaluator_output}\n"
                       if evaluator_output else "")
    prompt = JUDGE_PROMPT.format(
        criteria_block=criteria_block, iteration=iteration, candidate=candidate,
        evidence=evidence, evaluator_block=evaluator_block, score_lines_hint=score_lines_hint)
    resp = await relay.complete(
        model=settings.classification_model, max_tokens=2048,
        messages=[{"role": "user", "content": prompt}])
    out = parse_judge_output(resp.text, criteria)
    # The parser's fallback can capture the "ASI (highest-leverage direction):" header into the
    # value (e.g. when the model writes "highest-leverage_direction" with an underscore so the
    # precise pattern misses). Strip any leaked header so the ASI is just the actionable text.
    if out.asi:
        out.asi = re.sub(r"^\s*ASI\b[^\n:]*:\s*", "", out.asi, flags=re.IGNORECASE).strip()
    return out


def _record_judged_iteration(db_path, job_id, phase, iteration, judgment, seed_scores,
                             regressed, key_change, candidate_preview):
    """Write one simmer_iterations row + its criterion_details, matching the artifact contract
    the frontend reads (scores, composite, asi, judge_mode, criterion_details[])."""
    scores = judgment.scores or {}
    iter_id = str(uuid.uuid4())
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO simmer_iterations (id, job_id, phase, iteration, scores, composite, key_change, asi, judge_mode, regressed, candidate_preview) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (iter_id, job_id, phase, iteration, json.dumps(scores), judgment.composite,
             key_change, judgment.asi, "relay-judge", regressed, candidate_preview),
        )
        for crit, score in scores.items():
            conn.execute(
                "INSERT INTO simmer_criterion_details (id, iteration_id, criterion, score, seed_score, evidence, improve) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), iter_id, crit, score,
                 (seed_scores or {}).get(crit, score),
                 judgment.reasoning.get(crit, ""), judgment.asi),
            )
        conn.commit()
    finally:
        conn.close()
    return iter_id


async def simmer_loop(*, phase, job_id, db_path, settings, criteria, iterations,
                      seed_candidate, generate_fn, evidence, evaluator_fn=None):
    """Canonical generate→evaluate→judge→reflect loop with decomposed, non-agentic primitives.

    - seed_candidate: the iteration-0 candidate (from the decomposed generator).
    - generate_fn(candidate, asi) -> str: the decomposed generator. Receives candidate + ASI only.
    - evidence: pre-built corpus evidence string handed to the judge (no tools).
    - evaluator_fn(candidate) -> str|None: optional deterministic measurement for the judge.

    Returns (best_candidate, best_composite). Records every iteration to simmer_iterations.
    """
    candidate = seed_candidate
    seed_scores = None
    best = (-1.0, candidate)
    prev_comp = None
    for i in range(iterations + 1):
        evaluator_output = await evaluator_fn(candidate) if evaluator_fn else None
        judgment = await relay_judge(candidate, evidence, criteria, settings,
                                     iteration=i, evaluator_output=evaluator_output)
        if i == 0:
            seed_scores = judgment.scores
        comp = judgment.composite
        regressed = prev_comp is not None and comp < prev_comp
        _record_judged_iteration(
            db_path, job_id, phase, i, judgment, seed_scores, regressed,
            key_change=("seed" if i == 0 else "regenerated from ASI"),
            candidate_preview=candidate[:500])
        print(f"  [{phase}] iter {i}: {comp}/10 scores={judgment.scores} asi={(judgment.asi or '')[:80]!r}", flush=True)
        if comp > best[0]:
            best = (comp, candidate)
        prev_comp = comp
        if i < iterations and judgment.asi:
            candidate = await generate_fn(candidate, judgment.asi)
    return best[1], best[0]
