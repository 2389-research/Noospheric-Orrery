"""Entity names must survive the trip to the traversal endpoints intact.

A name is free-form text produced by extraction, so it contains whatever the source
documents contained. Putting it in a URL PATH loses two classes of name outright, and
both were reachable in production:

- `/` — 1331 of 57155 active names in a real graph (2.3%). Percent-encoding does not
  save it: the server decodes the path before routing, so `%2F` becomes a separator
  again and the extra segment matches no route.
- `.` and `..` — dot segments, which the HTTP client normalises away before the request
  is even sent. `/graph/neighborhood/..` leaves the client as `/graph`, so the caller
  gets a different endpoint's body reported as this entity's neighborhood.

The query-parameter spelling is opaque to both. These tests pin that, and the path
spelling stays covered because ids still use it.
"""

import pytest


def _seed(store, names):
    c = store.conn
    c.execute("INSERT INTO documents (id, title) VALUES ('d0', 'doc')")
    for i, n in enumerate(names):
        c.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, 'Concept')",
                  (f"e{i}", n))
        c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES (?, 'd0')", (f"e{i}",))
    c.commit()


# The awkward set. Each one broke, or could break, a different layer.
HOSTILE_NAMES = [
    "io/reader",        # path separator — the 2.3% case
    "a/b/c",            # several separators
    "..",               # dot segment: client-side normalisation to another endpoint
    ".",                # ditto
    ".gitignore",       # leading dot, but NOT a dot segment — must keep working
    "what?",            # query delimiter
    "issue#42",         # fragment delimiter
    "50% off",          # percent, which is the escape character itself
    "a b",              # space
]


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_a_name_survives_the_query_spelling(test_client, test_store, name):
    _seed(test_store, [name])
    r = test_client.get("/graph/neighborhood", params={"name": name, "depth": 1, "max_nodes": 5})
    assert r.status_code == 200, f"{name!r} did not resolve: {r.text[:200]}"
    assert r.json()["seed"]["name"] == name


@pytest.mark.parametrize("name", ["io/reader", "..", "."])
def test_the_path_spelling_still_cannot_carry_these(test_client, test_store, name):
    """Documents the limitation rather than pretending it was fixed.

    `httpx` (which TestClient uses) normalises the dot segments, and `/` re-splits into
    segments that match no route — so these do NOT resolve through the path form. That
    is exactly why the client moved to `?name=`. If a future change makes the path form
    work, this test fails and should be deleted deliberately, not silently.
    """
    _seed(test_store, [name])
    from urllib.parse import quote
    r = test_client.get(f"/graph/neighborhood/{quote(name, safe='')}")
    assert r.status_code != 200 or r.json().get("seed", {}).get("name") != name


def test_ids_still_resolve_through_the_path_form(test_client, test_store):
    """The path spelling is kept for ids and existing callers, so it must keep working."""
    _seed(test_store, ["ordinary"])
    r = test_client.get("/graph/neighborhood/e0")
    assert r.status_code == 200
    assert r.json()["seed"]["id"] == "e0"


def test_both_entities_survive_on_the_two_entity_routes(test_client, test_store):
    """shared-context and paths take TWO names, so they had two of the same hole."""
    _seed(test_store, ["io/reader", "pkg/mod"])
    for path in ("/graph/shared-context", "/graph/paths"):
        r = test_client.get(path, params={"a": "io/reader", "b": "pkg/mod"})
        assert r.status_code == 200, f"{path} failed: {r.text[:200]}"
        body = r.json()
        assert body["entity_a"]["name"] == "io/reader"
        assert body["entity_b"]["name"] == "pkg/mod"


def test_a_missing_name_is_a_422_not_a_crash(test_client, test_store):
    """Neither spelling supplied: the route must reject it rather than resolving None."""
    _seed(test_store, ["ordinary"])
    assert test_client.get("/graph/neighborhood").status_code == 422
