# ABOUTME: Reusable simmer framework — the generate→evaluate→judge→reflect loop, decomposed.
# ABOUTME: Non-agentic relay judge (reuses simmer-sdk's parser) + loop + iteration recording.
#
# ┌─────────────────────────────────────────────────────────────────────────────────────────┐
# │ CHESTERTON'S FENCE — read CLAUDE.md "Simmer pipeline — READ THE THEORY BEFORE TOUCHING IT" │
# │ and simmer-sdk/docs/spec.md before changing this file.                                     │
# │ The generate / evaluate / judge / reflect / ASI stages each prevent a SPECIFIC documented  │
# │ failure. They are not boilerplate. Do NOT collapse the judge into the generator, strip the │
# │ judge's calibration, or hand the generator the scores/evaluator output "to simplify" — that │
# │ reintroduces the failures the design prevents (see the #27 case study in CLAUDE.md).        │
# │ Structural invariants are enforced by tests/test_simmer_core.py; if you change the shape,   │
# │ those go red on purpose.                                                                    │
# └─────────────────────────────────────────────────────────────────────────────────────────┘
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
from simmer_sdk.prompts import build_judge_prompt

from ..db import get_connection


# Injected ahead of the judge skill for our non-agentic relay judge: the skill assumes the judge
# can investigate via tools, but here everything (candidate + source material + evaluator output)
# is pre-loaded into the prompt. This adapts the same skill for a single bounded call.
NON_AGENTIC_JUDGE_PREAMBLE = (
    "You are running WITHOUT tools. Everything you need — the candidate, the full source material, "
    "and any evaluator output — is included inline below. Do NOT attempt to read or investigate "
    "files; there are none. Read the provided content, then score and produce your ASI in the "
    "required format. Respond directly; do not use extended thinking."
)


async def relay_judge(candidate: str, evidence: str, criteria: dict, settings, *,
                      iteration: int = 0, evaluator_output: str | None = None,
                      seed_candidate: str | None = None, seed_scores: dict | None = None,
                      problem_class: str = "text/creative"):
    """Non-agentic judge: ONE relay.complete call, everything pre-loaded, no tools.

    Builds the prompt with simmer-sdk's own build_judge_prompt — so it carries the full judge
    SKILL (the canonical definition of what an ASI is and how to construct it), seed calibration
    (seed candidate + seed scores anchor cross-iteration scoring), and evaluator-output
    interpretation ("the evaluator informs your judgment, it doesn't replace it"). Parsed with
    simmer-sdk's parse_judge_output. Runs through orrery-relay so think:false applies.

    FENCE: do NOT replace build_judge_prompt with a hand-rolled prompt. We tried that — a bare
    prompt drops the judge skill, so gemma had no reference for what an ASI is and returned empty
    "**" ASIs with wildly swinging scores. The skill IS the contract. Do NOT give this judge tools
    / make it agentic either: that path stalls local models (~185s/judge) — evidence is why this
    is one bounded call with the evidence pre-loaded.
    """
    relay = Relay.from_settings(settings)
    prompt = build_judge_prompt(
        iteration=iteration, artifact_type="text", problem_class=problem_class,
        criteria=criteria, candidate=candidate,
        seed_candidate=seed_candidate, seed_scores=seed_scores,
        evaluator_output=evaluator_output,
        judge_preamble=NON_AGENTIC_JUDGE_PREAMBLE,
        # deliberately NO candidate_path/evaluator_path → no "read the files" instruction
    )
    # The skill expects to investigate source files; non-agentic, so inject the corpus / answer-key
    # inline. This is what the judge scores coverage/precision against.
    prompt += ("\n\nSOURCE MATERIAL — judge the candidate strictly against THIS "
               "(provided inline; do not use tools):\n" + evidence)
    resp = await relay.complete(
        model=settings.classification_model, max_tokens=3072,
        messages=[{"role": "user", "content": prompt}])
    out = parse_judge_output(resp.text, criteria)
    # The parser's fallback can capture the "ASI (highest-leverage direction):" header into the
    # value (e.g. when the model writes "highest-leverage_direction" with an underscore so the
    # precise pattern misses). Strip any leaked header so the ASI is just the actionable text.
    if out.asi:
        out.asi = re.sub(r"^\s*ASI\b[^\n:]*:\s*", "", out.asi, flags=re.IGNORECASE).strip()
    return out


def _record_judged_iteration(db_path, job_id, phase, iteration, judgment, seed_scores,
                             regressed, key_change, candidate_preview, judge_mode="relay-judge"):
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
             key_change, judgment.asi, judge_mode, regressed, candidate_preview),
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
                      seed_candidate, generate_fn, evidence, evaluator_fn=None,
                      problem_class="text/creative",
                      judge_fn=None, judge_mode="relay-judge"):
    """Canonical generate→evaluate→judge→reflect loop with decomposed, non-agentic primitives.

    - seed_candidate: the iteration-0 candidate (from the decomposed generator).
    - generate_fn(candidate, asi) -> str: the decomposed generator. Receives candidate + ASI only.
    - evidence: pre-built corpus evidence string handed to the judge (no tools).
    - evaluator_fn(candidate) -> str|None: optional deterministic measurement for the judge.
    - problem_class: "text/creative" (no evaluator — golden) or "pipeline/engineering" (the judge
      interprets the evaluator output, e.g. F1, alongside the criteria — spec phase).

    The iteration-0 candidate + its scores become the SEED CALIBRATION reference handed to the
    judge on every later iteration, so cross-iteration scores are anchored (not cold guesses).

    Returns (best_candidate, best_composite). Records every iteration to simmer_iterations.
    """
    judge = judge_fn or relay_judge
    candidate = seed_candidate
    seed_artifact = seed_candidate   # fixed iteration-0 reference for judge calibration
    seed_scores = None
    best = (-1.0, candidate)
    prev_comp = None
    for i in range(iterations + 1):
        evaluator_output = await evaluator_fn(candidate) if evaluator_fn else None
        judgment = await judge(
            candidate, evidence, criteria, settings,
            iteration=i, evaluator_output=evaluator_output,
            seed_candidate=seed_artifact, seed_scores=seed_scores,  # build_judge_prompt gates on iteration>0
            problem_class=problem_class)
        if i == 0:
            seed_scores = judgment.scores
        comp = judgment.composite
        regressed = prev_comp is not None and comp < prev_comp
        _record_judged_iteration(
            db_path, job_id, phase, i, judgment, seed_scores, regressed,
            key_change=("seed" if i == 0 else "regenerated from ASI"),
            candidate_preview=candidate[:500],
            judge_mode=judge_mode)
        print(f"  [{phase}] iter {i}: {comp}/10 scores={judgment.scores} asi={(judgment.asi or '')[:80]!r}", flush=True)
        if comp > best[0]:
            best = (comp, candidate)
        prev_comp = comp
        if i < iterations and judgment.asi:
            candidate = await generate_fn(candidate, judgment.asi)
    return best[1], best[0]
