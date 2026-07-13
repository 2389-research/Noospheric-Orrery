"""Read-consistency: invalidated entities must not surface in the galaxy graph.

`get_trade_routes` derives domain-to-domain edges from `entity_sources`, so a
soft-deleted (invalid_at) entity must be excluded — otherwise a human who
invalidates an entity via the corrections flow still sees its trade routes in
the /graph viz.
"""


def _seed_cross_domain(store):
    """One entity (e1) mentioned in two docs in two different domains → exactly
    one alpha↔beta trade route derived from that shared entity."""
    c = store.conn
    c.execute("INSERT INTO documents (id, title) VALUES ('d1', 'doc1')")
    c.execute("INSERT INTO documents (id, title) VALUES ('d2', 'doc2')")
    c.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) "
              "VALUES ('d1', 'alpha', 1, 1.0)")
    c.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) "
              "VALUES ('d2', 'beta', 1, 1.0)")
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'shared-thing', 'Concept')")
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd1')")
    c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd2')")
    c.commit()


def test_trade_route_present_before_invalidation(test_store):
    _seed_cross_domain(test_store)
    routes = test_store.relationships.get_trade_routes()
    assert routes == [{"source": "alpha", "target": "beta", "weight": 1}]


def test_invalidated_entity_excluded_from_trade_routes(test_store):
    from src.pipeline.graph_repair import apply_invalidation

    _seed_cross_domain(test_store)
    apply_invalidation(test_store.conn, "e1", reason="test")

    routes = test_store.relationships.get_trade_routes()
    # The only cross-domain link came from e1, now invalidated → no routes.
    assert routes == []
