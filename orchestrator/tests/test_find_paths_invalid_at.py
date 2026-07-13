"""Read-consistency: find_paths must not traverse invalidated edges.

The BFS over co_occurs relationships must skip edges with invalid_at set,
otherwise a path can route through an entity a human has invalidated (whose
incident edges are marked invalid by apply_invalidation).
"""


def _seed_chain(store):
    c = store.conn
    for eid, name in [("a", "alpha"), ("mid", "middle"), ("b", "beta")]:
        c.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, ?)", (eid, name, "Concept"))
    c.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight) "
              "VALUES ('r1', 'a', 'mid', 'co_occurs', 1)")
    c.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight) "
              "VALUES ('r2', 'mid', 'b', 'co_occurs', 1)")
    c.commit()


def test_find_paths_present_when_all_valid(test_client, test_store):
    _seed_chain(test_store)
    resp = test_client.get("/graph/paths/a/b")
    assert resp.status_code == 200
    assert len(resp.json()["paths"]) >= 1


def test_find_paths_excludes_path_through_invalidated_entity(test_client, test_store):
    from src.pipeline.graph_repair import apply_invalidation

    _seed_chain(test_store)
    # Invalidating 'mid' also marks its incident edges (r1, r2) invalid.
    apply_invalidation(test_store.conn, "mid", reason="test")

    resp = test_client.get("/graph/paths/a/b")
    assert resp.status_code == 200
    assert resp.json()["paths"] == []
