"""The trace-reader seam: how this package gets a run's per-node activity.

`tracker`'s `activity.jsonl` schema and its distiller belong to tracker, not to us —
they will drift on their own schedule. So this package does not parse raw traces. It
declares the narrow shape it needs (`TraceReader`) and takes an implementation, exactly
the way `orrery_codesum` takes an already-constructed relay instead of importing an SDK.

Two calls is the whole protocol:

    find_runs(root)     -> [run_dir, ...]
    load_run(run_dir)   -> RunTrace

`distill_reader(distill)` adapts tracker's own `distill` module to it, so the wide
5-function surface stays confined to one adapter that a schema change can break in
exactly one place. Tests use a hand-built fake reader — no tracker install required.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .coerce import as_obj


@dataclass
class NodeTrace:
    """One node's own recorded activity. `text` is node-local — it must not contain
    run-level framing, or the node summary stops being node-local."""
    id: str
    text: str
    kind: str | None = None
    model: str | None = None
    outcome: str | None = None


@dataclass
class RunTrace:
    run_id: str
    nodes: list[NodeTrace]
    run_label: str | None = None
    rung: str | None = None
    manifest: dict = field(default_factory=dict)


def _find_corpus_manifest(run_dir: str, max_depth: int = 8) -> dict:
    """Walk up for a corpus-level MANIFEST.json mapping run_id -> run metadata.

    Optional: a lone run has no corpus manifest, and then run_label falls back to the
    run's own directory name.
    """
    d = run_dir
    for _ in range(max_depth):
        d = os.path.dirname(d)
        if not d or d == os.sep:
            break
        mf = os.path.join(d, "MANIFEST.json")
        if os.path.exists(mf):
            try:
                with open(mf, encoding="utf-8", errors="replace") as f:
                    rows = json.load(f)
                return {e.get("run_id"): e for e in rows}
            except (OSError, ValueError, AttributeError, TypeError):
                return {}
    return {}


def strip_run_header(distilled: str) -> str:
    """Drop the leading RUN/goal/source lines from a distilled trace.

    Without this the per-node input carries the run's goal and overall framing, and the
    "describe only what THIS node did" instruction is fighting context that contradicts
    it. Node-local means node-local.
    """
    i = distilled.find("\nNODE ")
    return distilled[i + 1:] if i >= 0 else distilled


def distill_reader(distill):
    """Adapt tracker's `distill` module to the TraceReader protocol.

    Expects the module surface: find_runs, read_log, load_manifest, build, render_run.
    Only nodes with recorded turns are returned — a declared node that never ran has no
    activity to summarize.
    """

    class _DistillReader:
        def find_runs(self, root: str) -> list[str]:
            return distill.find_runs(root)

        def load_run(self, run_dir: str) -> RunTrace:
            rows = distill.read_log(os.path.join(run_dir, "activity.jsonl"))
            # The manifest is JSON off disk: `x or {}` would let a scalar through to the
            # first .get() below. Same for its nested `vars`. See coerce.py.
            man = as_obj(distill.load_manifest(run_dir))
            built = distill.build(rows, man)

            run_id = os.path.basename(run_dir)
            entry = as_obj(_find_corpus_manifest(run_dir).get(run_id))
            rung = entry.get("rung_label_in_dip") or as_obj(man.get("vars")).get("rung")

            nodes = []
            for n in built:
                if not n.turns:  # declared but never executed
                    continue
                text = strip_run_header(distill.render_run(run_dir, only_node=n.id)[0])
                nodes.append(NodeTrace(
                    id=n.id, text=text, kind=n.kind, model=n.model, outcome=n.outcome,
                ))

            return RunTrace(
                run_id=run_id, nodes=nodes,
                run_label=entry.get("run") or run_id, rung=rung, manifest=man,
            )

    return _DistillReader()
