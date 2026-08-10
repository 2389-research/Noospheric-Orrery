"""Level-specific summarization prompts + the summarize_fn factory.

Mirrors `orrery_codesum.summarize`: this module owns the PROMPTS, `runs.py` owns the
orchestration. Two levels only —

  - "dip"  — recognize the workflow's design patterns against the closed catalog
  - "node" — summarize ONE node's own recorded activity

This package stays dependency-free: it receives an already-constructed `relay`
(duck-typed with `.complete_sync(model=, messages=, max_tokens=, system=,
temperature=, ollama_options=)` returning an object with a `.text` attribute).

Two prompt invariants that are load-bearing, not stylistic:

1. **Node summaries are node-local.** The model sees one node's trace and is told not
   to judge overall run success or reference other nodes. A run does not know whether
   it succeeded — that is observed externally, from the user moving on — so letting
   run-level outcome leak into a node summary would manufacture a judgement the
   corpus does not contain, and contaminate any downstream retrospective.
2. **Summaries are neutral.** Nothing asks "what went wrong." Ingested runs are
   summarized the way a repo is; evaluating a trajectory is a separate downstream job
   for an agent reading the graph.

`num_ctx` matters here: node traces and dips are long, and Ollama truncates the
prompt silently from the left at its small default context. `_OLLAMA_OPTIONS` raises
it; the kwarg is ignored by non-Ollama backends.
"""
from __future__ import annotations

from .catalog import DIP_CATALOG

# Long inputs (a whole dip + the catalog; a full node trace). Without this, Ollama
# cuts the head off the prompt and the model summarizes a fragment — with no error.
_OLLAMA_OPTIONS = {"num_ctx": 8192}

NODE_SYSTEM = """You summarize ONE node of an agentic code-generation run, for a knowledge graph.
You see ONLY this node's own recorded activity (turns, tool calls, results).
RULES: describe only what THIS node did, in order. Do NOT judge overall run success, do NOT
reference other nodes / external scores, do NOT speculate. Every concrete thing you name (a
file path, command, symbol, outcome) MUST appear in the trace.
OUTPUT exactly:
WHAT IT DID: <4-8 sentence factual narrative, in order>
ARTIFACTS: <bulleted; each file it wrote with path, and notable commands/results>
SELF-REPORTED OUTCOME: <the node's own final status if the trace states one, else "not stated">
"""

NODE_USER = "=== NODE TRACE (this node's own activity only) ===\n{content}\n\n=== YOUR SUMMARY ===\n"

DIP_USER = "=== DIP ===\n{content}\n\n=== ANALYSIS ===\n"

# level -> (system, user_template, max_tokens)
_LEVELS = {
    "dip": (DIP_CATALOG, DIP_USER, 900),
    "node": (NODE_SYSTEM, NODE_USER, 700),
}


def make_summarize_fn(relay, model: str):
    """Build a level-dispatching summarize_fn used by `summarize_run`.

    Call as summarize_fn(level, content=...) where level is "dip" or "node".
    Returns the summary string. Deterministic (temperature 0) so a re-run over the
    same corpus reproduces the same summaries.
    """

    def summarize_fn(level: str, *, content: str = "") -> str:
        try:
            system, template, max_tokens = _LEVELS[level]
        except KeyError:
            raise ValueError(f"unknown summarization level: {level!r}")

        response = relay.complete_sync(
            model=model,
            messages=[{"role": "user", "content": template.format(content=content)}],
            max_tokens=max_tokens,
            system=system,
            temperature=0.0,
            ollama_options=_OLLAMA_OPTIONS,
        )
        return response.text.strip()

    return summarize_fn
