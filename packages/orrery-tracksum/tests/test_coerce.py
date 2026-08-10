"""The degrade-don't-crash contract for JSON read off disk.

A batch is a long, model-expensive job; losing all of it to one truncated file is the
worst available failure. These cases are the shapes `json.load` accepts happily and every
`.get()` / `set.add()` / `sorted()` afterwards does not.
"""
import pytest

from orrery_tracksum.coerce import as_obj, as_records, as_str

NON_OBJECTS = [None, 42, 3.5, "a string", [], ["a"], True]


@pytest.mark.parametrize("x", NON_OBJECTS)
def test_as_obj_replaces_non_objects(x):
    assert as_obj(x) == {}


def test_as_obj_passes_objects_through_unchanged():
    d = {"a": 1}
    assert as_obj(d) is d


@pytest.mark.parametrize("x", [None, 42, "a string", {"a": 1}, True])
def test_as_records_requires_a_list(x):
    assert as_records(x) == []


def test_as_records_keeps_only_object_entries():
    assert as_records([{"a": 1}, None, "s", 7, ["nested"], {"b": 2}]) == [{"a": 1}, {"b": 2}]


@pytest.mark.parametrize("x", [None, 42, 3.5, [], ["a"], {}, {"a": 1}, True])
def test_as_str_replaces_non_strings(x):
    assert as_str(x) == ""


def test_as_str_passes_strings_through():
    assert as_str("gemma4:26b") == "gemma4:26b"
    assert as_str("") == ""


def test_the_or_idiom_this_replaces_is_insufficient():
    """`x or {}` handles null but hands a scalar straight to the crash — the exact bug
    this module exists to prevent."""
    scalar = "not-an-object"
    assert (scalar or {}) is scalar          # survives the idiom
    with pytest.raises(AttributeError):
        (scalar or {}).get("anything")       # ...and raises at the dereference
    assert as_obj(scalar).get("anything") is None  # coerced instead
