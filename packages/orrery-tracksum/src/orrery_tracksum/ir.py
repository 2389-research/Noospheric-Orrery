"""Facts read straight out of a run's compiled `workflow.ir.json` — no model involved.

The IR is the ground truth about what the pipeline *declares*; the trace is what
actually *ran*. Keeping these separate is what makes the coherency check meaningful
(see `runs.coherency`).
"""
from __future__ import annotations

import json
import os
import re

from .coerce import as_obj, as_records, as_str

IR_FILENAME = "workflow.ir.json"

# A negated guard is NOT a failure-only guard: `when ctx.outcome != "fail"` and
# `when not fail` both contain "fail" but describe the happy path. Substring matching
# alone would mark the node they lead to as a safety net, which suppresses the
# completeness warning for a genuinely-missing mandatory node.
_NEGATION_RE = re.compile(r"!|\bnot\b")


def _load_ir(run_dir: str) -> dict:
    """The parsed IR, or {} for anything unusable.

    Guards on `isinstance(dict)`: json.load happily returns a list or a scalar for a
    truncated/garbage file, and every caller does `.get()` — so without this an
    `workflow.ir.json` containing `[]` aborts the whole batch with an AttributeError
    instead of degrading to empty facts for that one run.
    """
    try:
        with open(os.path.join(run_dir, IR_FILENAME), encoding="utf-8", errors="replace") as f:
            ir = json.load(f)
    except (OSError, ValueError):
        return {}
    return as_obj(ir)


def _nodes(ir: dict) -> list[dict]:
    """Declared nodes with a usable string ID.

    An ID is used as a dict key throughout (`kinds`, `role`, `incoming`), so a non-string
    one is not merely wrong, it is unhashable and would raise.
    """
    return [n for n in as_records(ir.get("Nodes")) if isinstance(n.get("ID"), str)]


def is_failure_guard(raw: str | None) -> bool:
    """Does this edge condition guard on failure (`fail` / `exhausted`)?

    A heuristic over `Condition.Raw`, deliberately biased toward "mandatory": an empty
    condition is unguarded, a negated one is treated as the happy path, and only a
    positive fail/exhaust mention counts. Erring this way means an odd condition
    produces a spurious completeness *warning* rather than silently hiding a missing
    node.
    """
    cond = as_str(raw).strip().lower()
    if not cond or _NEGATION_RE.search(cond):
        return False
    return ("fail" in cond) or ("exhaust" in cond)


def ir_facts(run_dir: str) -> dict:
    """Static shape of the declared workflow: name, node count/ids/kinds, models used.

    `node_count` is the DECLARED node count, which is legitimately larger than the
    number of nodes that ran — conditional safety-net nodes only fire on failure.
    """
    ir = _load_ir(run_dir)
    if not ir:
        return {}
    nodes = _nodes(ir)
    # Model names go into a set and then through sorted(), so a non-string is either
    # unhashable (a list raises on add) or poisons the sort by being incomparable with
    # the strings beside it. as_str drops both.
    models = set()
    for n in nodes:
        model = as_str(as_obj(n.get("Config")).get("Model"))
        if model:
            models.add(model)
    default_model = as_str(as_obj(ir.get("Defaults")).get("Model"))
    if default_model:
        models.add(default_model)
    return {
        "workflow": ir.get("Name"),
        "node_count": len(nodes),
        "node_ids": [n.get("ID") for n in nodes],
        "kinds": {n.get("ID"): n.get("Kind") for n in nodes},
        "models": sorted(models),
    }


def classify_nodes(run_dir: str) -> dict:
    """Split declared nodes into "mandatory" (happy path) vs "conditional" (safety net).

    A node is CONDITIONAL iff every incoming edge is guarded by a failure condition
    (`fail` / `exhausted`) — e.g. a Repair node whose only route in is `when exhausted`.
    Otherwise MANDATORY. Start is always mandatory.

    This is what lets the coherency check avoid a false alarm: a 34-node pipeline where
    10 nodes ran is not incomplete, because the dip itself declares that the other 24
    only run on failure. Comparing against the raw declared node count reports every
    healthy run as broken.

    Incoming-edge heuristic, read from the IR's edge guards (see `is_failure_guard`)
    rather than node names.
    """
    ir = _load_ir(run_dir)
    if not ir:
        return {}
    start = ir.get("Start")
    incoming: dict[str, list[bool]] = {}
    for e in as_records(ir.get("Edges")):
        to = e.get("To")
        if not isinstance(to, str):  # unusable as a key, and names no node
            continue
        incoming.setdefault(to, []).append(is_failure_guard(as_obj(e.get("Condition")).get("Raw")))
    role = {}
    for n in _nodes(ir):
        nid = n.get("ID")
        inc = incoming.get(nid, [])
        role[nid] = "conditional" if (nid != start and inc and all(inc)) else "mandatory"
    return role
