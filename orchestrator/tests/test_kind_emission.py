import uuid
from src.db import init_db, get_connection, recompute_cooccurrence


def _mk(conn, ent, doc, chunk):
    conn.execute("INSERT OR IGNORE INTO entities (id, canonical_name, type) VALUES (?,?,?)",
                 (ent, ent, "concept"))
    conn.execute("INSERT OR IGNORE INTO documents (id, title, content, content_hash) VALUES (?,?,?,?)",
                 (doc, doc, "x", doc))
    conn.execute("INSERT OR IGNORE INTO chunks (id, document_id, chunk_index, offset, length, text) "
                 "VALUES (?,?,0,0,1,'x')", (chunk, doc))
    conn.execute("INSERT INTO entity_sources (entity_id, document_id, chunk_id) VALUES (?,?,?)",
                 (ent, doc, chunk))


def test_agent_report_collection_docs_emit_no_edges(tmp_path):
    """Two docs sharing a chunk, both members of a collection whose provenance_kind is
    agent_report -> the a-b edge must NOT be emitted (opinion docs shouldn't reshape
    shared edge weights)."""
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    collection_id = str(uuid.uuid4())
    conn.execute("INSERT INTO collections (id, name, path, root_path, provenance_kind) "
                 "VALUES (?,?,?,?,?)", (collection_id, "reports", "reports", "/tmp", "agent_report"))
    _mk(conn, "a", "d1", "k1"); _mk(conn, "b", "d1", "k1")
    conn.execute("UPDATE documents SET silo_id = ? WHERE id = 'd1'", (collection_id,))
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    rows = conn.execute("SELECT COUNT(*) c FROM relationships WHERE type='co_occurs'").fetchone()
    assert rows["c"] == 0


def test_human_vault_collection_docs_emit_edges(tmp_path):
    """Same shape, but the silo's provenance_kind is human_vault -> the edge IS present.
    Confirms the kind gate doesn't suppress non-agent_report emission."""
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    collection_id = str(uuid.uuid4())
    conn.execute("INSERT INTO collections (id, name, path, root_path, provenance_kind) "
                 "VALUES (?,?,?,?,?)", (collection_id, "notes", "notes", "/tmp", "human_vault"))
    _mk(conn, "a", "d1", "k1"); _mk(conn, "b", "d1", "k1")
    conn.execute("UPDATE documents SET silo_id = ? WHERE id = 'd1'", (collection_id,))
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    rows = {(r["from_entity"], r["to_entity"]): r["weight"] for r in conn.execute(
        "SELECT from_entity, to_entity, weight FROM relationships WHERE type='co_occurs'")}
    assert rows == {("a", "b"): 1}


def test_agent_report_watched_source_vault_emits_no_edges(tmp_path):
    """Spec B6: a watched_sources vault silo with provenance_kind='agent_report' and NO
    document_collections membership row at all. This is the case the old
    document_collections.emits_cooccurrence lever could not reach -- the whole point of
    gating via silo_kind instead of collection membership."""
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    source_id = str(uuid.uuid4())
    conn.execute("INSERT INTO watched_sources (id, type, uri, provenance_kind) VALUES (?,?,?,?)",
                 (source_id, "vault", "/vaults/agent-reports", "agent_report"))
    _mk(conn, "a", "d1", "k1"); _mk(conn, "b", "d1", "k1")
    conn.execute("UPDATE documents SET silo_id = ?, source_id = ? WHERE id = 'd1'",
                 (source_id, source_id))
    conn.commit()
    # Sanity: no document_collections row exists for d1 -- the non-collection path.
    assert conn.execute(
        "SELECT COUNT(*) c FROM document_collections WHERE document_id = 'd1'"
    ).fetchone()["c"] == 0
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    rows = conn.execute("SELECT COUNT(*) c FROM relationships WHERE type='co_occurs'").fetchone()
    assert rows["c"] == 0


def test_human_vault_watched_source_emits_edges(tmp_path):
    """Same watched_sources (non-collection) shape, but provenance_kind='human_vault' ->
    the edge IS present."""
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    source_id = str(uuid.uuid4())
    conn.execute("INSERT INTO watched_sources (id, type, uri, provenance_kind) VALUES (?,?,?,?)",
                 (source_id, "vault", "/vaults/notes", "human_vault"))
    _mk(conn, "a", "d1", "k1"); _mk(conn, "b", "d1", "k1")
    conn.execute("UPDATE documents SET silo_id = ?, source_id = ? WHERE id = 'd1'",
                 (source_id, source_id))
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    rows = {(r["from_entity"], r["to_entity"]): r["weight"] for r in conn.execute(
        "SELECT from_entity, to_entity, weight FROM relationships WHERE type='co_occurs'")}
    assert rows == {("a", "b"): 1}
