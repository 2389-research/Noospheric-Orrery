"""The derived collection reads, and the domain-neighbours route.

Both cover things that fail SILENTLY rather than loudly, which is why they get tests
instead of a manual check: a co-occurrence edge that should not exist looks exactly like
one that should, and a missing route surfaces as an empty panel section because the
caller treats the fetch as optional.
"""

import pytest


def _seed_collection_with_summary(store):
    """Two leaf docs that share an entity, plus a rollup doc that mentions everything.

    This is the shape every collection ingest produces: `emits_cooccurrence = 1` on the
    files, `0` on the summary. The summary is the trap — it mentions every entity under
    it, so counting it makes unrelated collections look related.
    """
    c = store.conn
    c.execute("INSERT INTO collections (id, name, path) VALUES ('c1', 'repo-one', 'repo-one')")
    c.execute("INSERT INTO collections (id, name, path) VALUES ('c2', 'repo-two', 'repo-two')")
    for did, cid, emits in [("leaf1", "c1", 1), ("leaf2", "c2", 1),
                            ("rollup1", "c1", 0), ("rollup2", "c2", 0)]:
        c.execute("INSERT INTO documents (id, title) VALUES (?, ?)", (did, did))
        c.execute("INSERT INTO document_collections "
                  "(document_id, collection_id, role, emits_cooccurrence) VALUES (?, ?, ?, ?)",
                  (did, cid, "leaf" if emits else "root", emits))
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'shared thing', 'Concept')")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e2', 'summary only', 'Concept')")
    # e1 is mentioned in both LEAVES — a legitimate shared-entity route.
    for d in ("leaf1", "leaf2"):
        c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', ?)", (d,))
    # e2 is mentioned ONLY in the two rollups — it must produce no route at all.
    for d in ("rollup1", "rollup2"):
        c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e2', ?)", (d,))
    c.commit()


def test_summary_documents_do_not_manufacture_collection_routes(test_store):
    """`emits_cooccurrence` is the explicit replacement for the old `level == 'file'`
    test. A derived read that ignores it reinstates exactly what the column was added to
    remove — and the resulting edge is indistinguishable from a real one."""
    _seed_collection_with_summary(test_store)
    routes = test_store.collections.get_collection_routes()

    assert len(routes) == 1, (
        "only the entity shared between two LEAVES may produce a route; the rollups "
        f"share an entity too but opted out — got {routes}")
    assert {routes[0]["source"], routes[0]["target"]} == {"c1", "c2"}
    assert routes[0]["weight"] == 1


def test_weights_ignore_opted_out_memberships(test_store):
    """Same opt-out on the other derived read: a summary mentions everything beneath it,
    so counting it drags every entity's mass toward the wordiest rollup."""
    _seed_collection_with_summary(test_store)
    weights = test_store.collections.get_collection_weights()

    assert "e2" not in weights, "an entity seen only in opted-out documents has no collection mass"
    assert set(weights["e1"]) == {"c1", "c2"}
    assert abs(sum(weights["e1"].values()) - 1.0) < 1e-9, "shares are normalized"


def test_the_domain_neighbours_route_exists_and_answers(test_client, test_store):
    """The domain panel called this path before any route served it, so it 404'd — and
    because the caller treats trade routes as optional, the panel just showed nothing.
    A test that only checked the repository helper would have stayed green."""
    c = test_store.conn
    for i in range(2):
        c.execute("INSERT INTO documents (id, title) VALUES (?, ?)", (f"d{i}", f"doc {i}"))
        c.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) "
                  "VALUES (?, ?, 1, 1.0)", (f"d{i}", "alpha" if i == 0 else "beta"))
    c.execute("INSERT INTO domains (id, path, document_count) VALUES ('a', 'alpha', 1)")
    c.execute("INSERT INTO domains (id, path, document_count) VALUES ('b', 'beta', 1)")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'shared', 'Concept')")
    for d in ("d0", "d1"):
        c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', ?)", (d,))
    c.commit()

    resp = test_client.get("/graph/domain/alpha/neighbours?limit=6")
    assert resp.status_code == 200, "the route the panel already calls must exist"
    body = resp.json()
    assert body["domain"] == "alpha"
    assert [n["path"] for n in body["neighbours"]] == ["beta"]


def test_a_hierarchical_domain_path_survives_the_route(test_client, test_store):
    """Domain paths contain `/`, so the segment must be a `:path` converter. With a
    plain `{domain_path}` this 404s — and only a nested path shows it."""
    c = test_store.conn
    c.execute("INSERT INTO domains (id, path, document_count) VALUES ('n', 'software/tools', 0)")
    c.commit()

    resp = test_client.get("/graph/domain/software/tools/neighbours")
    assert resp.status_code == 200
    assert resp.json()["domain"] == "software/tools"
