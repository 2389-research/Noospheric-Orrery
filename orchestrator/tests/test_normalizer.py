from src.pipeline.normalizer import normalize_entity
from src.db import get_connection

def test_merge_map_hit(test_db):
    conn = get_connection(test_db)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'wet blending', 'Technique')")
    conn.execute("INSERT INTO merge_map (from_name, to_entity_id) VALUES ('wet-blending', 'e1')")
    conn.commit()
    entity_id = normalize_entity(conn, "wet-blending", "Technique")
    assert entity_id == "e1"
    conn.close()

def test_exact_match_existing(test_db):
    conn = get_connection(test_db)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'wet blending', 'Technique')")
    conn.commit()
    entity_id = normalize_entity(conn, "wet blending", "Technique")
    assert entity_id == "e1"
    conn.close()

def test_new_entity_inserted(test_db):
    conn = get_connection(test_db)
    entity_id = normalize_entity(conn, "drybrushing", "Technique")
    assert entity_id is not None
    row = conn.execute("SELECT canonical_name FROM entities WHERE id = ?", (entity_id,)).fetchone()
    assert row[0] == "drybrushing"
    conn.close()
