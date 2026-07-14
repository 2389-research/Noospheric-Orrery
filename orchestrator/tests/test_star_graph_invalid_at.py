"""Read-consistency: an invalidated entity has no star graph.

get_star_graph seeds from the entity row; if it doesn't filter invalid_at, a
soft-deleted entity still returns a viewable star (used by /entities/{id}).
"""


def test_star_graph_present_for_valid_entity(test_store):
    c = test_store.conn
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'thing', 'Concept')")
    c.commit()
    assert test_store.relationships.get_star_graph("e1") is not None


def test_star_graph_none_for_invalidated_entity(test_store):
    from src.pipeline.graph_repair import apply_invalidation

    c = test_store.conn
    c.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'thing', 'Concept')")
    c.commit()
    apply_invalidation(test_store.conn, "e1", reason="test")

    assert test_store.relationships.get_star_graph("e1") is None
