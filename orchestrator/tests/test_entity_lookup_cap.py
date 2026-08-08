"""Entity lookup by name must not be capped.

Every traversal endpoint resolves its argument through `_resolve_entity`, which used to
fetch `entities.list(limit=500)` and scan client-side. Past 500 entities — which any
real graph exceeds — a lookup by name returned 404 for an entity that plainly exists.
Worse, which 500 you got depended on the default ordering, so the same query could work
one day and 404 the next, which reads as flakiness rather than a bug.

Driven through the HTTP endpoint rather than the primitive, because the cap lived in the
route layer: testing the SQL alone would pass while the endpoint still 404s.
"""

import pytest

_ENTITIES = 700          # comfortably past the old 500 cap
_TARGET = "zzz findable"


@pytest.fixture
def big_graph(test_store):
    c = test_store.conn
    c.execute("INSERT INTO documents (id, title) VALUES ('d0', 'doc')")
    for i in range(_ENTITIES):
        c.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, 'Concept')",
                  (f"e{i:04d}", f"entity {i:04d}"))
        c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES (?, 'd0')",
                  (f"e{i:04d}",))
    # Sorts last by name, so any client-side scan of a truncated page misses it.
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('zz', ?, 'Concept')",
              (_TARGET,))
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('zz', 'd0')")
    c.commit()
    return test_store


def test_neighborhood_resolves_a_name_past_the_old_cap(test_client, big_graph):
    r = test_client.get(f"/graph/neighborhood/{_TARGET}")
    assert r.status_code == 200, r.text
    assert r.json()["seed"]["id"] == "zz"


def test_lookup_is_case_insensitive(test_client, big_graph):
    r = test_client.get(f"/graph/neighborhood/{_TARGET.upper()}")
    assert r.status_code == 200
    assert r.json()["seed"]["id"] == "zz"


def test_a_genuinely_missing_entity_still_404s(test_client, big_graph):
    """The fix must not turn "not found" into a false positive."""
    assert test_client.get("/graph/neighborhood/no such entity").status_code == 404
