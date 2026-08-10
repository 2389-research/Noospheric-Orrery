"""The production reader path: `distill_reader` over a fake distill module.

Every other test injects a `RunTrace` directly, which is right for exercising
`summarize_run` but leaves the adapter — the one place tracker's log format is touched —
unexercised. These tests drive it with a stand-in `distill` so no tracker install is
needed, which is the whole point of the injected-reader seam.
"""
import json
import types

import pytest

from orrery_tracksum import distill_reader, strip_run_header


class FakeNode:
    """Shape `distill.build` returns: id/kind/model/outcome + recorded turns."""

    def __init__(self, id, turns=1, kind="agent", model="haiku", outcome="success"):
        self.id, self.turns, self.kind = id, turns, kind
        self.model, self.outcome = model, outcome


def fake_distill(manifest, nodes=None, runs=("/corpus/run-1",)):
    """A module-shaped stand-in exposing the 5 functions the adapter expects."""
    nodes = nodes if nodes is not None else [FakeNode("Build")]
    return types.SimpleNamespace(
        find_runs=lambda root: list(runs),
        read_log=lambda path: [{"row": 1}],
        load_manifest=lambda run_dir: manifest,
        build=lambda rows, man: nodes,
        render_run=lambda run_dir, only_node=None: (
            "RUN header line\ngoal: something\nNODE %s\nran: node --test src/a.js\n" % only_node,
            None,
        ),
    )


def test_load_run_maps_nodes_and_manifest(tmp_path):
    reader = distill_reader(fake_distill({"terminal_status": "completed", "vars": {"rung": "R0"}}))
    trace = reader.load_run(str(tmp_path / "run-1"))

    assert trace.run_id == "run-1"
    assert trace.rung == "R0"
    assert trace.run_label == "run-1"  # no corpus MANIFEST.json -> falls back to dir name
    assert [n.id for n in trace.nodes] == ["Build"]
    assert trace.nodes[0].kind == "agent" and trace.nodes[0].model == "haiku"
    # the run-level header is stripped so node input is strictly node-local
    assert "goal:" not in trace.nodes[0].text
    assert trace.nodes[0].text.startswith("NODE Build")


@pytest.mark.parametrize("manifest", ["not-an-object", 42, ["a"], None, True])
def test_malformed_manifest_from_the_real_loader_degrades(tmp_path, manifest):
    """The nitpick this closes: the coercion in `load_run` was only covered by tests that
    injected a RunTrace directly, so a malformed manifest could still have raised HERE,
    before summarize_run ever ran."""
    reader = distill_reader(fake_distill(manifest))
    trace = reader.load_run(str(tmp_path / "run-1"))
    assert trace.manifest == {}
    assert trace.rung is None          # nested `vars` lookup degrades too
    assert [n.id for n in trace.nodes] == ["Build"]


@pytest.mark.parametrize("vars_value", ["scalar", 7, ["a"], None])
def test_malformed_vars_degrades(tmp_path, vars_value):
    reader = distill_reader(fake_distill({"vars": vars_value}))
    assert reader.load_run(str(tmp_path / "run-1")).rung is None


def test_nodes_without_recorded_turns_are_dropped(tmp_path):
    """A declared node that never executed has no activity to summarize."""
    nodes = [FakeNode("Build", turns=1), FakeNode("Repair", turns=0)]
    reader = distill_reader(fake_distill({}, nodes=nodes))
    assert [n.id for n in reader.load_run(str(tmp_path / "run-1")).nodes] == ["Build"]


def test_find_runs_delegates():
    reader = distill_reader(fake_distill({}, runs=("/a/run-1", "/a/run-2")))
    assert reader.find_runs("/a") == ["/a/run-1", "/a/run-2"]


def test_corpus_manifest_supplies_label_and_rung(tmp_path):
    """A corpus MANIFEST.json above the run dir names the run and its ladder rung."""
    corpus = tmp_path / "corpus"
    runs = corpus / "runs"
    runs.mkdir(parents=True)
    (corpus / "MANIFEST.json").write_text(json.dumps([
        {"run_id": "run-1", "run": "run4", "rung_label_in_dip": "R0"},
    ]))

    reader = distill_reader(fake_distill({}))
    trace = reader.load_run(str(runs / "run-1"))
    assert trace.run_label == "run4"
    assert trace.rung == "R0"


@pytest.mark.parametrize("payload", ['{"not": "a list"}', "[]", "42", "{bad json", '[null, 7]'])
def test_malformed_corpus_manifest_degrades(tmp_path, payload):
    corpus = tmp_path / "corpus"
    runs = corpus / "runs"
    runs.mkdir(parents=True)
    (corpus / "MANIFEST.json").write_text(payload)

    trace = distill_reader(fake_distill({})).load_run(str(runs / "run-1"))
    assert trace.run_label == "run-1"  # falls back to the dir name
    assert trace.rung is None


def test_strip_run_header_is_a_noop_without_a_node_marker():
    assert strip_run_header("no marker here") == "no marker here"
    assert strip_run_header("RUN x\nNODE A\nbody") == "NODE A\nbody"
