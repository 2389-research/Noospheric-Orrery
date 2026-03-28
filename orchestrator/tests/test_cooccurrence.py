from src.pipeline.cooccurrence import compute_cooccurrence_edges

def test_entities_in_same_chunk_get_edge():
    chunk_entities = {"c1": ["e1", "e2", "e3"], "c2": ["e1", "e2"]}
    edges = compute_cooccurrence_edges(chunk_entities)
    e1_e2 = [e for e in edges if set([e["from"], e["to"]]) == {"e1", "e2"}]
    assert len(e1_e2) == 1
    assert e1_e2[0]["weight"] == 2

def test_single_entity_chunk_no_edges():
    chunk_entities = {"c1": ["e1"]}
    edges = compute_cooccurrence_edges(chunk_entities)
    assert len(edges) == 0

def test_edge_has_source_chunk():
    chunk_entities = {"c1": ["e1", "e2"]}
    edges = compute_cooccurrence_edges(chunk_entities)
    assert edges[0]["source_chunk"] == "c1"
