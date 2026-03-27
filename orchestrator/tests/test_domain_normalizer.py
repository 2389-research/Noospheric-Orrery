from src.pipeline.domain_normalizer import normalize_domain_label, assign_document_domains
from src.db import init_db, get_connection

def test_exact_match_in_merge_map(test_db):
    conn = get_connection(test_db)
    conn.execute("INSERT INTO domains (id, path) VALUES ('d1', 'techniques/blending')")
    conn.execute("INSERT INTO domain_merge_map (from_label, to_path) VALUES ('wet blending', 'techniques/blending')")
    conn.commit()
    result = normalize_domain_label(conn, "wet blending")
    assert result == "techniques/blending"
    conn.close()

def test_new_domain_inserted(test_db):
    conn = get_connection(test_db)
    result = normalize_domain_label(conn, "techniques/airbrush")
    assert result == "techniques/airbrush"
    row = conn.execute("SELECT path FROM domains WHERE path = ?", ("techniques/airbrush",)).fetchone()
    assert row is not None
    conn.close()
