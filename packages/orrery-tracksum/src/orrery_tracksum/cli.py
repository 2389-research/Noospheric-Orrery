"""The eyeball loop — summarize runs (or one dip / one node trace) and print the result.

Kept as a first-class entry point on purpose. The catalog and the node prompt were
tuned by running a single artifact, reading the output, and adjusting; that loop is how
the compressed-catalog regression got caught (a condensed copy dropped the
discriminators paragraph and the model started reporting model-tiering as absent). A
prompt asset with no fast manual loop silently rots.

    python -m orrery_tracksum.cli runs <corpus_dir> [--out out/] [--model gemma4:26b]
    python -m orrery_tracksum.cli dip  <workflow.dip>
    python -m orrery_tracksum.cli node <node_trace.txt>

Requires `orrery-relay` and (for `runs`) tracker's `distill` on the path — pass its
directory with --distill-path.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .grounding import check_grounding
from .reader import distill_reader
from .runs import build_index, summarize_run, summarize_runs
from .summarize import make_summarize_fn


def _relay(model: str):
    """Build a relay from env settings. Local-first: defaults to the ollama backend."""
    from orrery_relay import Relay

    class _S:
        anthropic_backend = os.environ.get("ANTHROPIC_BACKEND", "ollama")
        ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        gateway_url = os.environ.get("GATEWAY_URL", "")
        gateway_api_key = os.environ.get("GATEWAY_API_KEY", "")
        aws_access_key = os.environ.get("AWS_ACCESS_KEY", "")
        aws_secret_key = os.environ.get("AWS_SECRET_KEY", "")
        aws_region = os.environ.get("AWS_REGION", "us-east-1")

    return make_summarize_fn(Relay.from_settings(_S()), model)


def _progress(event, **f):
    if event == "run_start":
        print("\n=== %s (%s)  run_id=%s  nodes=%d ===" % (
            f["run_label"], f["rung"], f["run_id"], f["nodes"]))
    elif event == "spec":
        print("  spec: %s (%d chars) fingerprint=%s" % (f["artifacts"], f["chars"], f["fingerprint"]))
    elif event == "dip":
        print("  dip: recognized (%d chars in); models (from IR)=%s" % (f["chars"], f["models"]))
    elif event == "node":
        flag = "⚠ " + str(f["ungrounded"]) if f["ungrounded"] else "ok"
        print("  node %-16s grounding %d/%d %s" % (f["node"], f["grounded"], f["named"], flag))
    elif event == "coherency":
        print("  coherency: completeness=%s (mandatory %d summarized, %d missing) | conditional fired %s" % (
            f["completeness_pass"], len(f["mandatory_agent_nodes"]) - len(f["missing_mandatory"]),
            len(f["missing_mandatory"]), f["conditional_fired"] or "none"))


def _cmd_runs(a) -> int:
    if a.distill_path:
        sys.path.insert(0, a.distill_path)
    try:
        import distill
    except ImportError:
        sys.exit("tracker's distill module not importable — pass --distill-path <dir>")

    summarize_fn = _relay(a.model)
    reader = distill_reader(distill)
    runs = reader.find_runs(a.root)
    if not runs:
        sys.exit("no runs found beneath %s" % a.root)
    print("summarizing %d run(s) with %s" % (len(runs), a.model))

    bundles = summarize_runs(a.root, summarize_fn, reader, on_progress=_progress)
    index = build_index(bundles)

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        for b in bundles:
            with open(os.path.join(a.out, b["run_label"] + ".json"), "w") as fh:
                json.dump(b, fh, indent=1)
        with open(os.path.join(a.out, "index.json"), "w") as fh:
            json.dump(index, fh, indent=1)
        print("\nwrote %d bundle(s) + index.json to %s" % (len(bundles), a.out))

    print("\n=== INDEX ===")
    for e in index:
        print("  %-6s %-10s nodes=%-2d dip=%s completeness=%s" % (
            e["run_label"], e["rung"], e["nodes"], e["dip_recognized"], e["completeness"]))
    return 0


def _cmd_one(a, level: str) -> int:
    with open(a.path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    out = _relay(a.model)(level, content=content)
    print("MODEL: %s   %s: %s" % (a.model, level, os.path.basename(a.path)))
    print("=" * 70)
    print(out)
    if level == "node":
        g = check_grounding(out, content)
        print("\n" + "-" * 70)
        print("GROUNDING: %d path(s) named, %d grounded" % (g["named"], g["grounded"]))
        print("  ⚠ UNGROUNDED: %s" % g["ungrounded"] if g["ungrounded"]
              else "  ✓ no ungrounded file-paths — faithful on artifacts")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="orrery_tracksum.cli")
    ap.add_argument("--model", default=os.environ.get("EXTRACTION_MODEL", "gemma4:26b"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("runs", help="summarize every run beneath a corpus dir")
    p.add_argument("root")
    p.add_argument("--out", default=None, help="write per-run JSONs + index.json here")
    p.add_argument("--distill-path", default=None, help="dir containing tracker's distill.py")

    for name in ("dip", "node"):
        q = sub.add_parser(name, help="summarize a single %s artifact" % name)
        q.add_argument("path")

    a = ap.parse_args(argv)
    if a.cmd == "runs":
        return _cmd_runs(a)
    return _cmd_one(a, a.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
