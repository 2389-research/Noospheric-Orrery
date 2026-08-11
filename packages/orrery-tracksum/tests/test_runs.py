"""End-to-end over a frozen fixture run, with a fake reader and a fake relay.

No tracker install, no model, no network — which is the point of the injected-reader
seam: tracker's activity.jsonl schema can change without breaking these.
"""
import json

import pytest

from orrery_tracksum import NodeTrace, RunTrace, build_index, coherency, summarize_run

from conftest import IR

NODE_TRACE = """NODE Build
ran: node --test src/store.js
wrote src/store.js
"""


class FakeReader:
    """Implements the whole TraceReader protocol: find_runs + load_run."""

    def __init__(self, run_dir, nodes, run_label="run4", rung="R0", manifest=None):
        self._run_dir, self._nodes = run_dir, nodes
        self._label, self._rung = run_label, rung
        self._manifest = manifest if manifest is not None else {
            "terminal_status": "completed", "totals": {"cost_usd": 1.25},
        }

    def find_runs(self, root):
        return [self._run_dir]

    def load_run(self, run_dir):
        return RunTrace(run_id="run-abc", nodes=self._nodes, run_label=self._label,
                        rung=self._rung, manifest=self._manifest)


def fake_summarize_fn(level, *, content=""):
    if level == "dip":
        return "NODE KINDS: agent, tool\nPATTERNS: gate-then-retry-loop — Gate->Build"
    return "WHAT IT DID: wrote src/store.js and ran its tests."


def test_summarize_run_produces_all_four_altitudes(run_dir, tmp_path):
    (tmp_path / "SPEC.md").write_text("product requirements")  # working_dir == run_dir here
    reader = FakeReader(run_dir, [NodeTrace(id="Build", text=NODE_TRACE, kind="agent", model="haiku")])

    out = summarize_run(run_dir, fake_summarize_fn, reader)

    assert out["run_label"] == "run4" and out["rung"] == "R0"
    assert "gate-then-retry-loop" in out["dip"]["recognized"]
    assert out["dip"]["ir_facts"]["node_count"] == 5  # declared shape, not executed
    assert out["spec"]["artifacts"] == ["SPEC.md"]
    assert len(out["nodes"]) == 1
    assert out["nodes"][0]["grounding"]["ungrounded"] == []
    # rollup is composed from facts, not generated — no model call could get it wrong
    assert "Run run4 (rung R0)" in out["rollup"] and "1 agent node(s): Build" in out["rollup"]
    assert out["metadata"] == {"terminal_status": "completed", "cost_usd": 1.25,
                               "trajectory": "unassigned"}


def test_trajectory_is_left_unassigned(run_dir):
    """A run cannot know its role in a search it is one attempt of — the ingestor
    decides chain position."""
    reader = FakeReader(run_dir, [NodeTrace(id="Build", text=NODE_TRACE)])
    assert summarize_run(run_dir, fake_summarize_fn, reader)["metadata"]["trajectory"] == "unassigned"


def test_completeness_ignores_unfired_conditional_nodes(run_dir):
    """The false-alarm guard: Repair is declared but only reachable `when exhausted`, so
    a run where it never fired is COMPLETE, not broken."""
    reader = FakeReader(run_dir, [NodeTrace(id="Build", text=NODE_TRACE, kind="agent")])
    checks = summarize_run(run_dir, fake_summarize_fn, reader)["coherency"]
    assert checks["completeness_pass"] is True
    assert checks["mandatory_agent_nodes"] == ["Build"]
    assert checks["conditional_agent_nodes"] == ["Repair"]
    assert checks["conditional_fired"] == []


def test_fired_repair_tier_is_reported_as_signal(run_dir):
    """A conditional node that ran is architecture signal, not an error."""
    reader = FakeReader(run_dir, [
        NodeTrace(id="Build", text=NODE_TRACE, kind="agent"),
        NodeTrace(id="Repair", text=NODE_TRACE, kind="agent"),
    ])
    checks = summarize_run(run_dir, fake_summarize_fn, reader)["coherency"]
    assert checks["conditional_fired"] == ["Repair"]
    assert checks["completeness_pass"] is True


def test_missing_mandatory_node_fails_completeness(run_dir):
    checks = coherency(run_dir, {"kinds": {"Build": "agent"}}, executed=set(), summarized=set())
    assert checks["completeness_pass"] is False
    assert checks["missing_mandatory"] == ["Build"]


def test_run_without_a_dip_still_summarizes(tmp_path):
    (tmp_path / "workflow.ir.json").write_text(json.dumps(IR))
    reader = FakeReader(str(tmp_path), [NodeTrace(id="Build", text=NODE_TRACE, kind="agent")])
    out = summarize_run(str(tmp_path), fake_summarize_fn, reader)
    assert out["dip"]["recognized"] is None
    assert len(out["nodes"]) == 1


def test_build_index_summarizes_the_batch(run_dir):
    reader = FakeReader(run_dir, [NodeTrace(id="Build", text=NODE_TRACE, kind="agent")])
    index = build_index([summarize_run(run_dir, fake_summarize_fn, reader)])
    # `file` records the filename the writer actually emitted, so a reader never has to
    # reconstruct `<run_label>.json` — which missed sanitised and de-duplicated names.
    assert index == [{"run_label": "run4", "file": "run4.json", "rung": "R0", "nodes": 1,
                      "dip_recognized": True, "completeness": True}]


# None is not in this list: FakeReader reads it as "use the default manifest". The null
# case is covered directly in test_coerce.
@pytest.mark.parametrize("manifest", ["not-an-object", 42, ["a"], True])
def test_malformed_manifest_degrades(run_dir, manifest):
    """The manifest is JSON off disk via the reader, so it is not guaranteed to be an
    object — and neither is its nested `totals`."""
    reader = FakeReader(run_dir, [NodeTrace(id="Build", text=NODE_TRACE, kind="agent")],
                        manifest=manifest)
    out = summarize_run(run_dir, fake_summarize_fn, reader)
    assert out["metadata"] == {"terminal_status": None, "cost_usd": None,
                               "trajectory": "unassigned"}


def test_malformed_totals_degrades(run_dir):
    reader = FakeReader(run_dir, [NodeTrace(id="Build", text=NODE_TRACE, kind="agent")],
                        manifest={"terminal_status": "completed", "totals": "not-an-object"})
    out = summarize_run(run_dir, fake_summarize_fn, reader)
    assert out["metadata"]["terminal_status"] == "completed"
    assert out["metadata"]["cost_usd"] is None


def test_progress_callback_receives_events(run_dir):
    reader = FakeReader(run_dir, [NodeTrace(id="Build", text=NODE_TRACE, kind="agent")])
    seen = []
    summarize_run(run_dir, fake_summarize_fn, reader, on_progress=lambda e, **f: seen.append(e))
    assert seen == ["run_start", "spec", "dip", "node", "coherency"]
