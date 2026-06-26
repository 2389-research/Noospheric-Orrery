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


def _extract_asi(text: str, criteria: dict) -> str:
    out = parse_judge_output(text, criteria)
    asi = (out.asi or "").strip()
    if asi:
        asi = re.sub(r"^\s*ASI\b[^\n:]*:\s*", "", asi, flags=re.IGNORECASE).strip()
    return asi


async def combine_outputs(outputs, criteria, settings, *, artifact_type, deliberations=None):
    """Count-agnostic COMBINE: median scores (SDK) + ONE synthesized ASI (synth-call).

    `outputs`: list of (name, raw_text, JudgeOutput). `deliberations`: list of (name, text) or None.
    Median handles scores deterministically. The ASI is synthesized by a single bounded relay call
    (build_synthesis_prompt). If that yields no usable ASI, fall back to the ASI of the judge whose
    weakest (lowest-consensus) criterion has the most headroom — deterministic, zero extra call.
    """
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
