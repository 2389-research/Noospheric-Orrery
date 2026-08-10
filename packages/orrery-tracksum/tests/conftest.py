import json

import pytest

# A miniature reliability lattice: happy path Stage -> Build -> Gate -> Finish, plus a
# Repair node reachable ONLY via `when exhausted`. This is the shape that made a naive
# "did every declared node run?" check report healthy runs as broken.
IR = {
    "Name": "MiniLattice",
    "Start": "Stage",
    "Defaults": {"Model": "haiku"},
    "Nodes": [
        {"ID": "Stage", "Kind": "tool"},
        {"ID": "Build", "Kind": "agent", "Config": {"Model": "haiku"}},
        {"ID": "Gate", "Kind": "tool"},
        {"ID": "Repair", "Kind": "agent", "Config": {"Model": "sonnet"}},
        {"ID": "Finish", "Kind": "tool"},
    ],
    "Edges": [
        {"From": "Stage", "To": "Build", "Condition": {"Raw": ""}},
        {"From": "Build", "To": "Gate", "Condition": {"Raw": ""}},
        {"From": "Gate", "To": "Build", "Condition": {"Raw": "when fail"}},
        {"From": "Gate", "To": "Repair", "Condition": {"Raw": "when exhausted"}},
        {"From": "Repair", "To": "Gate", "Condition": {"Raw": ""}},
        {"From": "Gate", "To": "Finish", "Condition": {"Raw": "when pass"}},
    ],
}


@pytest.fixture
def ir_dict():
    return IR


@pytest.fixture
def ir_dir(tmp_path):
    """A dir containing just workflow.ir.json."""
    (tmp_path / "workflow.ir.json").write_text(json.dumps(IR))
    return str(tmp_path)


@pytest.fixture
def run_dir(tmp_path):
    """A dir containing workflow.ir.json + workflow.dip — a minimal frozen run."""
    (tmp_path / "workflow.ir.json").write_text(json.dumps(IR))
    (tmp_path / "workflow.dip").write_text("workflow MiniLattice {}\n")
    return str(tmp_path)
