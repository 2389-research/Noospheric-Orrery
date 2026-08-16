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


def test_projection_weight_counts_shared_chunks(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    # a & b co-occur in 2 chunks, a & c in 1
    for ch in ("k1", "k2"):
        _mk(conn, "a", "d1", ch); _mk(conn, "b", "d1", ch)
    _mk(conn, "a", "d1", "k3"); _mk(conn, "c", "d1", "k3")
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b", "c"]); conn.commit()
    rows = {(r["from_entity"], r["to_entity"]): r["weight"] for r in conn.execute(
        "SELECT from_entity, to_entity, weight FROM relationships WHERE type='co_occurs'")}
    assert rows[("a", "b")] == 2
    assert rows[("a", "c")] == 1
    assert all(r["source_chunk"] is None for r in conn.execute(
        "SELECT source_chunk FROM relationships WHERE type='co_occurs'"))


def test_recompute_is_idempotent_and_scoped(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    for ch in ("k1", "k2"):
        _mk(conn, "a", "d1", ch); _mk(conn, "b", "d1", ch)
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()   # twice
    n = conn.execute("SELECT COUNT(*) c FROM relationships WHERE type='co_occurs'").fetchone()["c"]
    assert n == 1   # no duplicate from re-running


def test_invalidated_edge_is_preserved_not_revived(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    for ch in ("k1", "k2"):
        _mk(conn, "a", "d1", ch); _mk(conn, "b", "d1", ch)
    conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight, invalid_at) "
                 "VALUES (?, 'a', 'b', 'co_occurs', 99, CURRENT_TIMESTAMP)", (str(uuid.uuid4()),))
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    rows = conn.execute("SELECT weight, invalid_at FROM relationships WHERE type='co_occurs'").fetchall()
    assert len(rows) == 1 and rows[0]["invalid_at"] is not None   # invalidated kept, no valid dup


def test_invalidated_edge_preserved_regardless_of_endpoint_order(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    for ch in ("k1", "k2"):
        _mk(conn, "a", "d1", ch); _mk(conn, "b", "d1", ch)
    # invalidated row stored in the REVERSED endpoint order (as apply_merge may leave it)
    conn.execute("INSERT INTO relationships (id, from_entity, to_entity, type, weight, invalid_at) "
                 "VALUES (?, 'b', 'a', 'co_occurs', 99, CURRENT_TIMESTAMP)", (str(uuid.uuid4()),))
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    rows = conn.execute("SELECT invalid_at FROM relationships WHERE type='co_occurs'").fetchall()
    assert len(rows) == 1 and rows[0]["invalid_at"] is not None   # not revived under reversed order


def test_soft_deleted_entity_produces_no_edges(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    _mk(conn, "a", "d1", "k1"); _mk(conn, "b", "d1", "k1")
    conn.execute("UPDATE entities SET invalid_at = CURRENT_TIMESTAMP WHERE id = 'b'")
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM relationships WHERE type='co_occurs'").fetchone()["c"] == 0


def test_non_emitting_document_contributes_no_edges_even_when_entities_overlap(tmp_path):
    """A summary doc (emits_cooccurrence=0) shares entities with an emitting leaf doc.

    The projection must exclude the summary's chunk pairs entirely, or it reinstates
    the hub-node noise the flag exists to remove. This is the case a disjoint-entity
    fixture silently passes while shipping the regression.
    """
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    collection_id = str(uuid.uuid4())
    conn.execute("INSERT INTO collections (id, name, path, root_path) VALUES (?,?,?,?)",
                 (collection_id, "repo", "repo", "/tmp"))
    # leaf doc d_leaf: chunk kL has {a, b}  -> emits
    _mk(conn, "a", "d_leaf", "kL"); _mk(conn, "b", "d_leaf", "kL")
    conn.execute("INSERT INTO document_collections (document_id, collection_id, parent_path, role, "
                 "emits_cooccurrence) VALUES (?,?,?,'leaf',1)", ("d_leaf", collection_id, "repo/a.py"))
    # summary doc d_sum: chunk kS has {a, b, c, d}  -> does NOT emit (mentions everything)
    for ent in ("a", "b", "c", "d"):
        _mk(conn, ent, "d_sum", "kS")
    conn.execute("INSERT INTO document_collections (document_id, collection_id, parent_path, role, "
                 "emits_cooccurrence) VALUES (?,?,?,'group',0)", ("d_sum", collection_id, "repo/mod"))
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b", "c", "d"]); conn.commit()
    rows = {(r["from_entity"], r["to_entity"]): r["weight"] for r in conn.execute(
        "SELECT from_entity, to_entity, weight FROM relationships WHERE type='co_occurs'")}
    # Only the leaf's a-b edge, weight 1 (the summary's kS chunk contributes nothing).
    assert rows == {("a", "b"): 1}


def test_soft_deleted_document_contributes_no_edges(tmp_path):
    """A soft-invalidated document must not project co_occurs even if its entity_sources
    are somehow retained (defense-in-depth beyond the sync path clearing them)."""
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    _mk(conn, "a", "d1", "k1"); _mk(conn, "b", "d1", "k1")
    conn.execute("UPDATE documents SET invalid_at = CURRENT_TIMESTAMP WHERE id = 'd1'")
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM relationships WHERE type='co_occurs'").fetchone()["c"] == 0


def test_mixed_membership_uses_min_emits_gate(tmp_path):
    """A doc that is a leaf in one collection (emits=1) but a summary in another (emits=0)
    must be SUPPRESSED — MIN over memberships, not MAX."""
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    _mk(conn, "a", "d1", "k1"); _mk(conn, "b", "d1", "k1")
    conn.execute("INSERT INTO collections (id,name,path,root_path) VALUES ('c1','c1','c1','/x')")
    conn.execute("INSERT INTO collections (id,name,path,root_path) VALUES ('c2','c2','c2','/y')")
    conn.execute("INSERT INTO document_collections (document_id,collection_id,role,emits_cooccurrence) "
                 "VALUES ('d1','c1','leaf',1)")
    conn.execute("INSERT INTO document_collections (document_id,collection_id,role,emits_cooccurrence) "
                 "VALUES ('d1','c2','group',0)")
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b"]); conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM relationships WHERE type='co_occurs'").fetchone()["c"] == 0
