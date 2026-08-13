# ABOUTME: /graph/neighborhood sums a pair's co-occurrence rows into one weighted edge.
# ABOUTME: A pair can span several rows (per-chunk uploads + the aggregated code edge).
"""One edge, one weight — the sum of its rows.

Co-occurrence between two entities can be recorded across several `relationships` rows:
one per chunk from the upload path, plus the aggregated code-intent row. They are
contributions to the same edge. The route already collapsed them to one edge (an
`edge_set` dedup) but took a single row's weight and ordered neighbours by it — so the
reported strength was a fraction of the truth, and which neighbours survived the
`max_nodes` cut was decided on wrong numbers. The read now `SUM`s per pair.
"""
import uuid


def _entity(conn, name, etype="Thing"):
    eid = str(uuid.uuid4())
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, ?)", (eid, name, etype))
    # A source row so source_count > 0 and the node looks real.
    did = str(uuid.uuid4())
    conn.execute("INSERT INTO documents (id, title, content, content_hash, status) "
                 "VALUES (?, ?, 'x', ?, 'extracted')", (did, name + "-doc", "h-" + eid))
    conn.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES (?, ?)", (eid, did))
    return eid


def _cooccur(conn, a, b, weight, source_chunk=None):
    conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight, source_chunk) "
                 "VALUES (?, ?, ?, 'co_occurs', ?, ?)", (str(uuid.uuid4()), a, b, weight, source_chunk))


def test_neighborhood_edge_weight_is_the_sum_of_the_pair_rows(test_store, test_client):
    conn = test_store.conn
    a = _entity(conn, "alpha")
    b = _entity(conn, "beta")
    # Same pair, three separate contributions (two per-chunk + one aggregated).
    _cooccur(conn, a, b, 1, source_chunk="chunk-1")
    _cooccur(conn, a, b, 1, source_chunk="chunk-2")
    _cooccur(conn, a, b, 5, source_chunk=None)
    conn.commit()

    data = test_client.get(f"/graph/neighborhood?name={a}&depth=1").json()
    edges = [e for e in data["edges"] if {e["source"], e["target"]} == {a, b}]
    assert len(edges) == 1, f"expected one folded edge, got {edges}"
    assert edges[0]["weight"] == 7, f"weight should be 1+1+5, got {edges[0]['weight']}"


def test_neighbour_ordering_uses_the_summed_weight(test_store, test_client):
    """`max_nodes` truncates by weight, so the sum has to drive the ranking. A neighbour
    whose strength is spread across many small rows must outrank one with a single
    larger row when its total is greater."""
    conn = test_store.conn
    seed = _entity(conn, "seed")
    strong = _entity(conn, "strong")   # total 6, spread across 6 rows of weight 1
    weak = _entity(conn, "weak")       # total 4, one row
    for _ in range(6):
        _cooccur(conn, seed, strong, 1, source_chunk=str(uuid.uuid4()))
    _cooccur(conn, seed, weak, 4, source_chunk=None)
    conn.commit()

    data = test_client.get(f"/graph/neighborhood?name={seed}&depth=1&max_nodes=2").json()
    kept = {n["id"] for n in data["nodes"]} - {seed}
    assert strong in kept, "the stronger neighbour (summed) was dropped by max_nodes"
    strong_edge = [e for e in data["edges"] if {e["source"], e["target"]} == {seed, strong}][0]
    assert strong_edge["weight"] == 6


def test_an_invalidated_row_does_not_contribute_to_the_weight(test_store, test_client):
    conn = test_store.conn
    a = _entity(conn, "aa")
    b = _entity(conn, "bb")
    _cooccur(conn, a, b, 3, source_chunk=None)
    _cooccur(conn, a, b, 100, source_chunk="dead")
    conn.execute("UPDATE relationships SET invalid_at = CURRENT_TIMESTAMP WHERE source_chunk = 'dead'")
    conn.commit()

    data = test_client.get(f"/graph/neighborhood?name={a}&depth=1").json()
    edges = [e for e in data["edges"] if {e["source"], e["target"]} == {a, b}]
    assert len(edges) == 1
    assert edges[0]["weight"] == 3, "an invalidated row leaked into the summed weight"
