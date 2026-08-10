"""Coercions for values read out of JSON files on disk.

Everything this package consumes — a compiled `workflow.ir.json`, a run manifest, a
corpus MANIFEST — is a *file*, and a file can be truncated mid-write, hand-edited, or
produced by a different version of the writer. `json.load` succeeding says nothing about
the shape: a key expected to hold an object can hold `null`, a scalar, or a list, and
every one of those raises `AttributeError` / `TypeError` the moment it is `.get()`'d,
indexed, or added to a set.

The rule for this package: **degrade, don't crash.** One malformed run should summarize
to empty/partial facts, not abort a whole batch — a batch is a long, model-expensive
job, and losing all of it to one bad file is the worst possible failure.

Use these at every boundary where a JSON-sourced value is about to be dereferenced. The
`x or {}` idiom is NOT sufficient: it handles `null` but passes a scalar straight through
to the crash.
"""
from __future__ import annotations


def as_obj(x) -> dict:
    """`x` if it is a JSON object, else `{}` — for anything about to be `.get()`'d."""
    return x if isinstance(x, dict) else {}


def as_records(x) -> list[dict]:
    """The object records in `x`, dropping nulls, scalars, and nested lists.

    Malformed entries are dropped rather than guessed at, so a count over the result
    still means "well-formed records" — a null entry is not a record.
    """
    return [r for r in x if isinstance(r, dict)] if isinstance(x, list) else []


def as_str(x) -> str:
    """`x` if it is a string, else `""`.

    Guards both the obvious dereference (`(42).strip()`) and the subtler set/sort case:
    a non-string is either unhashable (`set.add([...])` raises) or poisons a later
    `sorted()` by being incomparable with the strings beside it.
    """
    return x if isinstance(x, str) else ""
