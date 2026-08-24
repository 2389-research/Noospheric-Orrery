from src.db import init_db, get_connection


def test_documents_has_silo_id_and_index(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    assert "silo_id" in cols
    idx = {r[1] for r in conn.execute("PRAGMA index_list(documents)")}
    assert any("silo" in name for name in idx)


def test_backfill_sets_silo_from_source_then_collection(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    # doc A: watched source only; B: collection only; C: both (source wins); D: neither
    conn.execute("INSERT INTO documents (id, title, source_id) VALUES ('A','a','src1')")
    conn.execute("INSERT INTO documents (id, title) VALUES ('B','b')")
    conn.execute("INSERT INTO collections (id, name, path, kind) VALUES ('col1','c','c','git_repo')")
    conn.execute("INSERT INTO document_collections (document_id, collection_id) VALUES ('B','col1')")
    conn.execute("INSERT INTO documents (id, title, source_id) VALUES ('C','c','src2')")
    conn.execute("INSERT INTO document_collections (document_id, collection_id) VALUES ('C','col1')")
    conn.execute("INSERT INTO documents (id, title) VALUES ('D','d')")
    conn.commit()
    from src.db import backfill_silo_ids
    backfill_silo_ids(conn)
    got = dict(conn.execute("SELECT id, silo_id FROM documents").fetchall())
    assert got == {"A": "src1", "B": "col1", "C": "src2", "D": None}
