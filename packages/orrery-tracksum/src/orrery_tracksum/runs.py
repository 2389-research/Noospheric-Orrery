"""Orchestration: a tracker run -> a neutral, multi-granularity summary bundle.

Mirrors `orrery_codesum.traverse` — this module owns the walk and assembly, the prompts
live in `summarize.py`. Per run it produces four altitudes so a consumer picks its own:

    rollup   — one line, composed from facts (no model call)
    spec     — the problem statement, verbatim
    dip      — the workflow's design patterns, recognized against the catalog
    nodes    — one summary per node that actually ran, node-local + grounding-checked

Plus `coherency`, which is the self-check that makes the batch trustworthy without a
human reading every summary.
"""
from __future__ import annotations

import os

from .coerce import as_obj
from .grounding import check_grounding
from .ir import classify_nodes, ir_facts
from .spec import gather_spec, working_dir_of

DIP_FILENAME = "workflow.dip"


def _rollup(run_label, rung, spec, node_ids) -> str:
    """One-line run overview, composed from facts rather than generated.

    Deliberately not a model call: everything in it is already known exactly, and a
    generated version could only introduce error.
    """
    artifacts = "+".join(a.replace(".md", "") for a in spec["artifacts"])
    return "Run %s (rung %s): spec=%s. Pipeline recognized from dip. %d agent node(s): %s." % (
        run_label, rung, artifacts, len(node_ids), ", ".join(node_ids),
    )


def coherency(run_dir: str, facts: dict, executed: set[str], summarized: set[str]) -> dict:
    """Did we summarize everything we should have, and which safety-nets fired?

    Completeness is checked over MANDATORY agent nodes only. Checking it against every
    declared node reports a healthy run as broken, because a reliability lattice
    declares many nodes that only run on failure (see `ir.classify_nodes`).

    `conditional_fired` is not an error signal — it is architecture signal. A repair
    tier that engaged tells you the pipeline hit a failure it was built to absorb, which
    is one of the more interesting things about a run.
    """
    role = classify_nodes(run_dir)
    kinds = facts.get("kinds", {})
    mandatory = {i for i, k in kinds.items() if k == "agent" and role.get(i) == "mandatory"}
    conditional = {i for i, k in kinds.items() if k == "agent" and role.get(i) == "conditional"}
    return {
        "completeness_pass": (mandatory <= summarized) if mandatory else None,
        "mandatory_agent_nodes": sorted(mandatory),
        "summarized_agent_nodes": sorted(summarized),
        "missing_mandatory": sorted(mandatory - summarized),
        "conditional_agent_nodes": sorted(conditional),
        "conditional_fired": sorted(conditional & executed),
    }


def summarize_run(run_dir: str, summarize_fn, reader, on_progress=None) -> dict:
    """Summarize one run into a bundle dict (the per-run JSON the ingest job consumes).

    `summarize_fn` is `summarize.make_summarize_fn(relay, model)`; `reader` implements
    the `reader.TraceReader` protocol. `on_progress(event, **fields)` is an optional
    callback for CLI/log output — this package never prints.
    """
    def _emit(event, **fields):
        if on_progress:
            on_progress(event, **fields)

    trace = reader.load_run(run_dir)
    facts = ir_facts(run_dir)
    run_label = trace.run_label or trace.run_id

    _emit("run_start", run_label=run_label, rung=trace.rung,
          run_id=trace.run_id, nodes=len(trace.nodes))

    # --- spec: verbatim, no model ---
    spec = gather_spec(working_dir_of(run_dir))
    _emit("spec", artifacts=spec["artifacts"], chars=spec["chars"], fingerprint=spec["fingerprint"])

    # --- dip: catalog recognition ---
    dip = {"recognized": None, "ir_facts": facts}
    dip_path = os.path.join(run_dir, DIP_FILENAME)
    if os.path.exists(dip_path):
        with open(dip_path, encoding="utf-8", errors="replace") as f:
            dip_text = f.read()
        dip["recognized"] = summarize_fn("dip", content=dip_text)
        _emit("dip", models=facts.get("models"), chars=len(dip_text))

    # --- nodes: node-local summary + grounding check ---
    node_summaries = []
    for n in trace.nodes:
        summary = summarize_fn("node", content=n.text)
        grounding = check_grounding(summary, n.text)
        node_summaries.append({
            "node": n.id, "kind": n.kind, "model": n.model, "self_outcome": n.outcome,
            "summary": summary, "grounding": grounding,
        })
        _emit("node", node=n.id, **grounding)

    executed = {n.id for n in trace.nodes}
    summarized = {n["node"] for n in node_summaries}
    checks = coherency(run_dir, facts, executed, summarized)
    _emit("coherency", **checks)

    # The manifest is JSON off disk (via the reader), so neither it nor its nested
    # `totals` is guaranteed to be an object — see coerce.py.
    manifest = as_obj(trace.manifest)
    totals = as_obj(manifest.get("totals"))
    return {
        "type": "run",
        "run_id": trace.run_id,
        "run_label": run_label,
        "rung": trace.rung,
        "source_path": run_dir,
        "metadata": {
            "terminal_status": manifest.get("terminal_status"),
            "cost_usd": totals.get("cost_usd"),
            # Position in a chain is decided by the INGESTOR (inferred from spec
            # similarity + order), not asserted here — a run cannot know its own role
            # in a search it is one attempt of.
            "trajectory": "unassigned",
        },
        "spec": spec,
        "dip": dip,
        "nodes": node_summaries,
        "rollup": _rollup(run_label, trace.rung, spec, [n.id for n in trace.nodes]),
        "coherency": checks,
    }


def summarize_runs(root: str, summarize_fn, reader, on_progress=None) -> list[dict]:
    """Summarize every run beneath `root`. Returns bundles in discovery order."""
    return [
        summarize_run(rd, summarize_fn, reader, on_progress=on_progress)
        for rd in reader.find_runs(root)
    ]


def build_index(bundles: list[dict], filenames: dict[int, str] | None = None) -> list[dict]:
    """The `index.json` the ingest job reads to find the per-run files.

    `filenames` maps a bundle's POSITION in `bundles` (the int from enumerate) to the
    file actually written. It
    matters because the writer sanitises and de-duplicates names: a label like `../x`
    becomes `_x.json` and a repeated `foo` becomes `foo~2.json`, so a reader that
    reconstructs `<run_label>.json` would miss those files entirely — and read `foo.json`
    twice. Recording the emitted name removes the guess. Omitted (or absent from an older
    index) it falls back to the label, which is correct for the common case where the
    label needed no transformation.
    """
    filenames = filenames or {}
    return [
        {
            "run_label": b["run_label"],
            "file": filenames.get(i, b["run_label"] + ".json"),
            "rung": b["rung"],
            "nodes": len(b["nodes"]),
            "dip_recognized": bool(b["dip"]["recognized"]),
            "completeness": b["coherency"]["completeness_pass"],
        }
        for i, b in enumerate(bundles)
    ]
