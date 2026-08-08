"""The primitive graph reads.

These exist for correctness, not tidiness. Each query carries two obligations that are
easy to forget and invisible once forgotten — the active-graph filter, and a bounded IN
clause — so the tests that matter are the ones proving those hold, and that the two bugs
the primitives were written to remove stay removed.
"""

import pytest

from src.repositories.graph_reads import (
    co_entities,
    degrees_of,
    domain_memberships,
    entities_by_ids,
    entities_in_domain,
    entity_by_name,
)


def _seed(store, *, entities=4, docs=3):
    c = store.conn
    for i in range(docs):
        c.execute("INSERT INTO documents (id, title) VALUES (?, ?)", (f"d{i}", f"doc {i}"))
        c.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, confidence)"
                  " VALUES (?, ?, 1, 1.0)", (f"d{i}", "alpha" if i % 2 == 0 else "alpha/deep"))
    c.execute("INSERT INTO domains (id, path, document_count) VALUES ('a', 'alpha', 2)")
    c.execute("INSERT INTO domains (id, path, document_count) VALUES ('ad', 'alpha/deep', 1)")
    for i in range(entities):
        c.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, 'Concept')",
                  (f"e{i}", f"entity {i}"))
        for j in range(i % docs + 1):
            c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES (?, ?)",
                      (f"e{i}", f"d{j}"))
    c.commit()


def _invalidate(store, entity_id):
    store.conn.execute("UPDATE entities SET invalid_at = datetime('now') WHERE id = ?",
                       (entity_id,))
    store.conn.commit()


# ── the two bugs these replace ──────────────────────────────────────────────

def test_name_lookup_is_not_capped(test_store):
    """The route layer and the MCP server each fetched `limit=500` and scanned
    client-side, so an entity past position 500 was reported "not found" — and which
    500 you got depended on the default ordering, so it presented as intermittent
    rather than broken. Ordering by name puts a 'z' name well past the cap."""
    c = test_store.conn
    for i in range(600):
        c.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, 'Concept')",
                  (f"e{i:04d}", f"entity {i:04d}"))
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('zz', 'zzz last', 'Concept')")
    c.commit()

    found = entity_by_name(test_store.conn, "zzz last")
    assert found is not None and found["id"] == "zz"


def test_id_lookups_survive_more_ids_than_sqlite_allows_bound_params(test_store):
    """Hand-rolled versions built one IN clause with no chunking, which raises past
    SQLITE_MAX_VARIABLE_NUMBER (~999) — reachable from a large domain or a wide
    subgraph, i.e. exactly where these reads are most useful."""
    c = test_store.conn
    ids = [f"e{i:05d}" for i in range(2500)]
    for i in ids:
        c.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, 'Concept')",
                  (i, f"name {i}"))
    c.commit()
    assert len(entities_by_ids(test_store.conn, ids)) == 2500
    assert len(degrees_of(test_store.conn, ids)) == 2500


# ── the filter, which is the other half of the point ────────────────────────

def test_every_primitive_excludes_invalidated_entities(test_store):
    """Assert it across the whole surface rather than one call at a time — the failure
    mode is a single query somewhere forgetting, which no per-call test would catch."""
    _seed(test_store)
    _invalidate(test_store, "e2")

    assert "e2" not in entities_by_ids(test_store.conn, ["e0", "e1", "e2", "e3"])
    assert entity_by_name(test_store.conn, "entity 2") is None
    assert "e2" not in domain_memberships(test_store.conn)
    assert "e2" not in {c["id"] for c in co_entities(test_store.conn, "e0")}
    assert "e2" not in {e["id"] for e in entities_in_domain(test_store.conn, "alpha")}


def test_lookup_can_opt_in_to_invalidated_for_the_dedup_path(test_store):
    """Not every missing filter is a bug. Re-ingest MUST see invalidated nodes so it
    re-attaches instead of resurrecting a duplicate, so the opt-out is deliberate and
    has to keep working."""
    _seed(test_store)
    _invalidate(test_store, "e1")
    assert set(entities_by_ids(test_store.conn, ["e0", "e1"], include_invalid=True)) == {"e0", "e1"}


def test_name_lookup_is_case_insensitive_and_deterministic(test_store):
    """Names are not unique, so a lookup has to break ties the same way every call or
    the same query returns different entities on different requests."""
    c = test_store.conn
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('b', 'Dup Name', 'A')")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('a', 'dup name', 'B')")
    c.commit()
    assert entity_by_name(test_store.conn, "DUP NAME")["id"] == "a"
    assert entity_by_name(test_store.conn, "dup name")["id"] == "a"


# ── the reads themselves ────────────────────────────────────────────────────

def test_degrees_counts_mentions(test_store):
    _seed(test_store)
    d = degrees_of(test_store.conn, ["e0", "e1", "e2", "e3"])
    assert d["e0"] == 1 and d["e1"] == 2 and d["e2"] == 3
    assert d["e3"] == 1  # 3 % 3 + 1


def test_memberships_are_normalized_and_scopeable(test_store):
    _seed(test_store)
    everything = domain_memberships(test_store.conn)
    assert abs(sum(everything["e2"].values()) - 1.0) < 1e-9
    scoped = domain_memberships(test_store.conn, ["e2"])
    assert set(scoped) == {"e2"} and scoped["e2"] == everything["e2"]


def test_co_entities_carry_the_shared_documents(test_store):
    """`shared_doc_ids` is load-bearing rather than decorative: callers place a
    co-entity relative to the documents it shares."""
    _seed(test_store)
    cos = co_entities(test_store.conn, "e2")
    assert cos, "e2 shares documents with other entities"
    assert all(c["shared_doc_ids"] for c in cos)
    assert cos == sorted(cos, key=lambda c: -c["weight"])
    assert "e2" not in {c["id"] for c in cos}, "an entity is not its own co-entity"


def test_co_entities_chunks_rather_than_truncates_the_scope(test_store):
    """Slicing doc_ids to one bound-parameter batch silently drops every document past
    the first 900, so a large scope returns incomplete weights AND incomplete
    shared_doc_ids — wrong numbers, no error."""
    c = test_store.conn
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('a', 'a', 'C')")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('b', 'b', 'C')")
    doc_ids = []
    for i in range(1200):
        did = f"doc{i:05d}"
        doc_ids.append(did)
        c.execute("INSERT INTO documents (id, title) VALUES (?, ?)", (did, did))
        c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('a', ?)", (did,))
        c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('b', ?)", (did,))
    c.commit()

    [co] = co_entities(test_store.conn, "a", doc_ids=doc_ids)
    assert co["id"] == "b"
    assert co["weight"] == 1200, "every chunk must contribute, not just the first"
    assert len(co["shared_doc_ids"]) == 1200


def test_entities_in_domain_can_include_subdomains(test_store):
    _seed(test_store)
    shallow = {e["id"] for e in entities_in_domain(test_store.conn, "alpha")}
    deep = {e["id"] for e in entities_in_domain(test_store.conn, "alpha", recursive=True)}
    assert shallow <= deep


def test_domain_neighbours_falls_back_when_nothing_is_materialized(test_store):
    """`domain_edges` is populated by a build that may never have run. A graph in that
    state must still answer, slowly, rather than claiming a domain has no neighbours."""
    from src.repositories.graph_reads import _domain_neighbours_live, domain_neighbours

    _seed(test_store, entities=6, docs=4)
    assert test_store.conn.execute("SELECT COUNT(*) FROM domain_edges").fetchone()[0] == 0
    live = _domain_neighbours_live(test_store.conn, "alpha")
    assert live, "precondition: the fixture links alpha to another domain"
    assert domain_neighbours(test_store.conn, "alpha") == live


def test_domain_neighbours_prefers_the_materialized_table(test_store):
    """When the table IS populated it must be used — otherwise the materialization
    buys nothing and the two paths can silently disagree."""
    from src.repositories.graph_reads import domain_neighbours

    _seed(test_store, entities=6, docs=4)
    test_store.conn.execute(
        "INSERT INTO domain_edges (source, target, weight) VALUES ('alpha', 'zeta', 99)")
    test_store.conn.commit()

    assert domain_neighbours(test_store.conn, "alpha") == [{"path": "zeta", "weight": 99}]
