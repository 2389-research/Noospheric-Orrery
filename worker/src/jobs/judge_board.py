# ABOUTME: Local multi-judge board — bounded relay calls reusing simmer-sdk's pure prompt
# ABOUTME: builders, median consensus, and parser. NEVER calls the SDK's agentic dispatch.
#
# CHESTERTON'S FENCE: see CLAUDE.md "Simmer pipeline" + the design doc
# docs/superpowers/specs/2026-06-26-local-multi-judge-board-design.md. This is the SAME pattern as
# relay_judge: everything pre-loaded inline, no tools, think:false via orrery-relay. Do NOT import
# or call simmer_sdk.judge_board's _dispatch_single_panelist (it is agentic and stalls gemma4).

import re
from orrery_relay import Relay
from simmer_sdk import JudgeOutput
from simmer_sdk.types import JudgeDefinition
from simmer_sdk.judge import parse_judge_output
from simmer_sdk.judge_board import compute_consensus_scores
from simmer_sdk.prompts import (
    build_board_panelist_prompt, build_deliberation_prompt, build_synthesis_prompt,
)
from simmer_sdk.primitives import get_primitives_for_judge

from .simmer_core import relay_judge, NON_AGENTIC_JUDGE_PREAMBLE

# Curated, orrery-owned lens menu (A). The composer (B) picks from THESE names only.
# Generic + criteria-driven so the same menu serves golden and spec phases.
LENS_LIBRARY: dict[str, str] = {
    "coverage_hawk": "Score from a recall lens: hunt for entities present in the source/golden that the candidate misses. Reward completeness; punish coverage gaps.",
    "precision_hawk": "Score from a precision lens: hunt for entities the candidate includes that are not real or are metadata (bare dates, ids, urls). Reward tight precision; punish noise.",
    "generalizability_skeptic": "Score from a generalization lens: does the artifact rely on general rules/type-definitions rather than hardcoded entity names? Reward what would work on unseen documents.",
    "taxonomy_purist": "Score from a taxonomy lens: are entity types meaningful, consistent, correctly assigned, and (for a domain) granular rather than generic?",
}

DEFAULT_PANEL = ["coverage_hawk", "precision_hawk"]   # fallback when composition fails

COMPOSER_PROMPT = """You are composing a small panel of evaluation judges. Choose the {n} MOST useful
lenses for evaluating a candidate against these criteria. Pick ONLY from the menu — do not invent.

CRITERIA:
{criteria}

MENU (choose by exact name):
{menu}

PROBLEM CLASS: {problem_class}

CANDIDATE (snippet of what is being evaluated):
{candidate}

Return ONLY the chosen lens names, one per line, at most {n}. No commentary."""


def _judges_from_names(names):
    """Map raw lines to JudgeDefinitions, tolerating local-model formatting
    ('- name', 'name: desc', '1. name'). First menu-matching token per line wins; dedup."""
    seen, out = set(), []
    for line in names:
        for token in re.findall(r"[a-z][a-z0-9_]*", line.lower()):
            if token in LENS_LIBRARY and token not in seen:
                seen.add(token)
                out.append(JudgeDefinition(name=token, lens=LENS_LIBRARY[token]))
                break   # one judge per line
    return out


async def resolve_panel(settings, criteria, candidate, *, problem_class):
    """Resolve the panel ONCE per run. Explicit JUDGE_PANEL list bypasses the composer;
    'auto' runs one bounded composer call that picks ≤N names FROM the menu. Falls back to
    DEFAULT_PANEL on empty/garbage. Always truncated to judge_count."""
    n = max(1, int(settings.judge_count))
    if settings.judge_panel and settings.judge_panel.strip().lower() != "auto":
        panel = _judges_from_names(settings.judge_panel.split(","))
        return (panel or _judges_from_names(DEFAULT_PANEL))[:n]
    menu = "\n".join(f"- {name}: {lens}" for name, lens in LENS_LIBRARY.items())
    crit = "\n".join(f"- {k}: {v}" for k, v in criteria.items())
    relay = Relay.from_settings(settings)
    try:
        resp = await relay.complete(
            model=settings.classification_model, max_tokens=256,
            messages=[{"role": "user", "content": COMPOSER_PROMPT.format(
                n=n, criteria=crit, menu=menu, problem_class=problem_class,
                candidate=str(candidate)[:1500])}])
        panel = _judges_from_names(resp.text.splitlines())[:n]
    except Exception as e:
        print(f"  [judge_board] composer failed: {e}", flush=True)
        panel = []
    return panel or _judges_from_names(DEFAULT_PANEL)[:n]


def _extract_asi(text: str, criteria: dict) -> str:
    out = parse_judge_output(text, criteria)
    asi = (out.asi or "").strip()
    if asi:
        asi = re.sub(r"^\s*ASI\b[^\n:]*:\s*", "", asi, flags=re.IGNORECASE).strip()
    return asi


async def relay_panelist(judge_def, candidate, evidence, criteria, settings, *,
                         iteration=0, evaluator_output=None, seed_candidate=None,
                         seed_scores=None, problem_class="text/creative"):
    """One panelist = ONE bounded relay.complete with a lens, everything pre-loaded inline, no tools.
    Mirror of relay_judge but built with build_board_panelist_prompt so it carries the lens +
    judge skill + board primitives. Returns (name, raw_text, JudgeOutput)."""
    relay = Relay.from_settings(settings)
    primitives = get_primitives_for_judge(
        has_evaluator=evaluator_output is not None, has_search_space=False)
    prompt = build_board_panelist_prompt(
        judge_def=judge_def, iteration=iteration, artifact_type="text",
        problem_class=problem_class, criteria=criteria, candidate=candidate,
        primitives=primitives, seed_candidate=seed_candidate, seed_scores=seed_scores,
        evaluator_output=evaluator_output, judge_preamble=NON_AGENTIC_JUDGE_PREAMBLE)
    prompt += ("\n\nSOURCE MATERIAL — judge the candidate strictly against THIS "
               "(provided inline; do not use tools):\n" + evidence)
    resp = await relay.complete(model=settings.classification_model, max_tokens=3072,
                                messages=[{"role": "user", "content": prompt}])
    out = parse_judge_output(resp.text, criteria)
    if out.asi:
        out.asi = re.sub(r"^\s*ASI\b[^\n:]*:\s*", "", out.asi, flags=re.IGNORECASE).strip()
    return judge_def.name, resp.text, out


async def combine_outputs(outputs, criteria, settings, *, artifact_type, deliberations=None):
    """Count-agnostic COMBINE: median scores (SDK) + ONE synthesized ASI (synth-call).

    `outputs`: list of (name, raw_text, JudgeOutput). `deliberations`: list of (name, text) or None.
    Median handles scores deterministically. The ASI is synthesized by a single bounded relay call
    (build_synthesis_prompt). If that yields no usable ASI, fall back to the ASI of the judge whose
    weakest (lowest-consensus) criterion has the most headroom — deterministic, zero extra call.
    """
    if not outputs:
        return JudgeOutput(scores={}, asi="", reasoning={})
    scores = compute_consensus_scores([o[2].scores for o in outputs])
    relay = Relay.from_settings(settings)
    prompt = build_synthesis_prompt(
        criteria=criteria,
        all_judge_outputs=[(name, raw) for name, raw, _ in outputs],
        deliberation_results=deliberations or [],
        artifact_type=artifact_type)
    resp = await relay.complete(model=settings.classification_model, max_tokens=2048,
                                messages=[{"role": "user", "content": prompt}])
    asi = _extract_asi(resp.text, criteria)
    if not asi:
        # pick-one fallback: target the weakest criterion, take that judge's ASI
        weakest = min(scores, key=scores.get) if scores else None
        best = None
        for _, _, jo in outputs:
            if weakest is not None and weakest in jo.scores:
                if best is None or jo.scores[weakest] <= best[0]:
                    best = (jo.scores[weakest], jo.asi)
        asi = (best[1] if best else (outputs[0][2].asi if outputs else "")) or ""
    reasoning = {}
    for _, _, jo in outputs:
        for k, v in (jo.reasoning or {}).items():
            reasoning.setdefault(k, v)
    return JudgeOutput(scores=scores, asi=asi, reasoning=reasoning)
