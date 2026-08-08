"""orchestrator/src/db.py and worker/src/db.py must not drift.

The two processes open the SAME database files. A table or index present in one and
missing from the other is not a style problem: whichever process opens a workspace
first decides its shape, and the other then reads a schema it does not expect.

That is a live hazard rather than a hypothetical — every table added in this change had
to be written into both files by hand, and nothing but this test makes a one-sided edit
visible.

Scoped deliberately to the shared graph surface rather than whole-file equality: the two
files legitimately differ elsewhere (busy_timeout, the orchestrator's per-process init
guard). If a divergence here is intentional, add it to `_ALLOWED_DIVERGENCE` with the
reason rather than deleting the assertion.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ORCH = _ROOT / "orchestrator" / "src" / "db.py"
_WORKER = _ROOT / "worker" / "src" / "db.py"

# Tables both processes write. Their DDL must match.
_MIRRORED_TABLES = ["graph_snapshot", "domain_edges", "collections",
                    "document_collections", "collection_edges"]

# Indexes on that surface. Table DDL alone is not enough: an index dropped from one
# file costs nothing structurally and everything in latency, so it is exactly the kind
# of drift that goes unnoticed.
_MIRRORED_INDEXES = ["idx_document_collections_collection",
                     "idx_entity_sources_entity", "idx_document_domains_path"]

_ALLOWED_DIVERGENCE: dict[str, str] = {
    # name -> why it is allowed to differ. Empty: nothing diverges today.
}


def _table_ddl(source: str, table: str) -> str | None:
    m = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", source, re.S)
    if not m:
        return None
    # Normalise whitespace and strip comments — layout may differ, meaning may not.
    body = re.sub(r"--[^\n]*", "", m.group(1))
    return re.sub(r"\s+", " ", body).strip()


def _join_adjacent_literals(source: str) -> str:
    """Splice Python implicit string concatenation back together.

    An index can be written inline in the SCHEMA text or built from adjacent string
    literals in a migration call, and the two files do not always agree on which.
    That is formatting, not drift, so normalise it away before comparing — otherwise
    this test fails on line wrapping and gets muted.
    """
    return re.sub(r'"\s*\n\s*"', "", source)


def _index_ddl(source: str, name: str) -> str | None:
    source = _join_adjacent_literals(source)
    m = re.search(rf"CREATE INDEX IF NOT EXISTS {name}\s+(ON[^\"';]*)", source, re.S)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


@pytest.mark.parametrize("table", _MIRRORED_TABLES)
def test_table_ddl_is_mirrored(table):
    if table in _ALLOWED_DIVERGENCE:
        pytest.skip(_ALLOWED_DIVERGENCE[table])
    orch, worker = _table_ddl(_ORCH.read_text(), table), _table_ddl(_WORKER.read_text(), table)
    assert orch is not None, f"`{table}` missing from orchestrator/src/db.py"
    assert worker is not None, f"`{table}` missing from worker/src/db.py"
    assert orch == worker, (
        f"the `{table}` DDL differs between the two db.py files. Both processes open "
        f"the same databases, so whichever opens a workspace first decides its shape.")


@pytest.mark.parametrize("name", _MIRRORED_INDEXES)
def test_index_is_mirrored(name):
    orch, worker = _index_ddl(_ORCH.read_text(), name), _index_ddl(_WORKER.read_text(), name)
    assert orch is not None, f"`{name}` missing from orchestrator/src/db.py"
    assert worker is not None, f"`{name}` missing from worker/src/db.py"
    assert orch == worker, f"the `{name}` index differs between the two db.py files"


def test_the_mirror_check_can_actually_fail():
    """Guard against the comparison silently matching nothing.

    Every assertion above compares two extractions. If the extractor returned None for
    both, they would be "equal" and the test would pass while checking nothing.
    """
    assert _table_ddl(_ORCH.read_text(), "no_such_table") is None
    assert _index_ddl(_ORCH.read_text(), "idx_no_such_index") is None
    assert _table_ddl(_ORCH.read_text(), "collections") is not None
    assert _index_ddl(_ORCH.read_text(), "idx_document_collections_collection") is not None
