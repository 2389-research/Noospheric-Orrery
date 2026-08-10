import json

import pytest

from orrery_tracksum import classify_nodes, ir_facts
from orrery_tracksum.ir import is_failure_guard


def test_ir_facts_reports_declared_shape_and_all_models(ir_dir):
    facts = ir_facts(ir_dir)
    assert facts["workflow"] == "MiniLattice"
    assert facts["node_count"] == 5
    assert facts["kinds"]["Repair"] == "agent"
    # per-node models AND the workflow default are both collected — two-tier model
    # economics is invisible if the default is dropped
    assert facts["models"] == ["haiku", "sonnet"]


def test_classify_nodes_marks_failure_only_nodes_conditional(ir_dir):
    role = classify_nodes(ir_dir)
    # Repair's only route in is `when exhausted` -> a safety net, not the happy path
    assert role["Repair"] == "conditional"
    # Build has an unguarded incoming edge (Stage->Build) as well as a `when fail`
    # retry edge, so it stays mandatory — "any unguarded route in" wins
    assert role["Build"] == "mandatory"
    assert role["Gate"] == "mandatory"
    assert role["Finish"] == "mandatory"  # `when pass` is not a failure guard
    assert role["Stage"] == "mandatory"   # Start, no incoming edges


def test_missing_or_unreadable_ir_returns_empty(tmp_path):
    assert ir_facts(str(tmp_path)) == {}
    assert classify_nodes(str(tmp_path)) == {}
    (tmp_path / "workflow.ir.json").write_text("{not json")
    assert ir_facts(str(tmp_path)) == {}
    assert classify_nodes(str(tmp_path)) == {}


@pytest.mark.parametrize("payload", ["[]", '["a"]', "42", '"a string"', "null"])
def test_non_object_ir_degrades_instead_of_crashing(tmp_path, payload):
    """json.load happily returns a list or scalar for a truncated file, and every caller
    does .get() — so one bad run must not abort the whole batch with AttributeError."""
    (tmp_path / "workflow.ir.json").write_text(payload)
    assert ir_facts(str(tmp_path)) == {}
    assert classify_nodes(str(tmp_path)) == {}


def test_malformed_nested_records_are_dropped_not_dereferenced(tmp_path):
    """The IR is a compiler artifact but still a file that can be truncated or
    hand-edited. Every nested field gets .get()'d, so one bad record must not abort the
    batch: nulls/scalars, a non-object Condition, a non-string ID or To, and a Nodes key
    that isn't even a list."""
    ir = {
        "Name": "Malformed",
        "Start": "A",
        "Defaults": "not-an-object",          # scalar where an object is expected
        "Nodes": [
            {"ID": "A", "Kind": "tool"},
            None,                              # null record
            "just a string",                   # scalar record
            {"ID": ["not", "a", "string"]},     # unhashable ID
            {"ID": "B", "Kind": "agent", "Config": "not-an-object"},
            {"ID": "C", "Kind": "agent", "Config": {"Model": "sonnet"}},
            # Non-string Model values: a list is unhashable (set.add raises) and an int
            # would poison sorted() by being incomparable with the strings beside it.
            {"ID": "D", "Kind": "agent", "Config": {"Model": ["a", "b"]}},
            {"ID": "E", "Kind": "agent", "Config": {"Model": 7}},
            {"ID": "F", "Kind": "agent", "Config": {"Model": {"name": "x"}}},
        ],
        "Edges": [
            None,
            42,
            {"From": "A", "To": {"bad": "key"}},          # unhashable To
            {"From": "A", "To": "B", "Condition": 7},      # non-object Condition
            {"From": "A", "To": "C", "Condition": {"Raw": 99}},  # non-string Raw
        ],
    }
    (tmp_path / "workflow.ir.json").write_text(json.dumps(ir))

    facts = ir_facts(str(tmp_path))
    assert facts["node_ids"] == ["A", "B", "C", "D", "E", "F"]  # records with usable IDs
    assert facts["node_count"] == 6
    # Only the one real string survives: scalar Config, scalar Defaults, and non-string
    # Model values all contribute nothing — and sorted() does not raise.
    assert facts["models"] == ["sonnet"]

    role = classify_nodes(str(tmp_path))
    assert set(role) == {"A", "B", "C", "D", "E", "F"}
    # Both surviving edges have unusable conditions -> not failure guards -> mandatory.
    assert role["B"] == "mandatory"
    assert role["C"] == "mandatory"


def test_nodes_key_that_is_not_a_list_degrades(tmp_path):
    (tmp_path / "workflow.ir.json").write_text(json.dumps({"Name": "X", "Nodes": {"a": 1}}))
    facts = ir_facts(str(tmp_path))
    assert facts["node_count"] == 0 and facts["node_ids"] == []
    assert classify_nodes(str(tmp_path)) == {}


@pytest.mark.parametrize("cond", ["when fail", "WHEN FAIL", "when exhausted", "fail"])
def test_positive_failure_guards_recognized(cond):
    assert is_failure_guard(cond) is True


@pytest.mark.parametrize("raw", [42, 3.5, [], {}, True])
def test_non_string_condition_raw_is_not_a_guard(raw):
    assert is_failure_guard(raw) is False


@pytest.mark.parametrize("cond", [
    "",
    None,
    "when pass",
    'when ctx.outcome != "fail"',   # negated — this is the happy path
    "when not fail",
    "when !exhausted",
])
def test_unguarded_and_negated_conditions_are_not_failure_guards(cond):
    """Biased toward "mandatory": an odd condition should produce a spurious
    completeness warning, never silently hide a missing mandatory node."""
    assert is_failure_guard(cond) is False


def test_negated_guard_keeps_its_target_mandatory(tmp_path, ir_dict):
    """A node reachable only by `!= fail` is on the happy path. Substring-matching
    "fail" would mark it conditional and suppress its completeness check."""
    ir = json.loads(json.dumps(ir_dict))  # deep copy
    ir["Nodes"].append({"ID": "Publish", "Kind": "agent"})
    ir["Edges"].append({"From": "Gate", "To": "Publish",
                        "Condition": {"Raw": 'when ctx.outcome != "fail"'}})
    (tmp_path / "workflow.ir.json").write_text(json.dumps(ir))
    assert classify_nodes(str(tmp_path))["Publish"] == "mandatory"
