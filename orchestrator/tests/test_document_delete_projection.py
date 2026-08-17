import os

os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")

from src.db import init_db, recompute_cooccurrence
from src.repositories.sqlite_store import SQLiteDataStore


def _add(conn, ent, doc, chunk):
    conn.execute("INSERT OR IGNORE INTO entities (id, canonical_name, type) VALUES (?,?,?)",
                 (ent, ent, "concept"))
    conn.execute("INSERT OR IGNORE INTO documents (id, title, content, content_hash) VALUES (?,?,?,?)",
                 (doc, doc, "x", doc))
    conn.execute("INSERT OR IGNORE INTO chunks (id, document_id, chunk_index, offset, length, text) "
                 "VALUES (?,?,0,0,1,'x')", (chunk, doc))
    conn.execute("INSERT INTO entity_sources (entity_id, document_id, chunk_id) VALUES (?,?,?)",
                 (ent, doc, chunk))


def _valid_edges(conn):
    return sorted((r["from_entity"], r["to_entity"], r["weight"]) for r in conn.execute(
        "SELECT from_entity, to_entity, weight FROM relationships "
        "WHERE type='co_occurs' AND invalid_at IS NULL"))


def test_delete_retracts_via_projection_not_the_inert_source_chunk_delete(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db)
    store = SQLiteDataStore(db)
    conn = store.conn

    # Two docs, each with a chunk holding {a, b}: a-b co-occurs in 2 chunks (weight 2).
    _add(conn, "a", "d1", "c1"); _add(conn, "b", "d1", "c1")
    _add(conn, "a", "d2", "c2"); _add(conn, "b", "d2", "c2")
    # A third entity c only in d1, so it orphans when d1 is deleted.
    _add(conn, "c", "d1", "c1")
    conn.commit()
    recompute_cooccurrence(conn, ["a", "b", "c"]); conn.commit()

    assert _valid_edges(conn) == sorted([("a", "b", 2), ("a", "c", 1), ("b", "c", 1)])

    store.documents.delete("d1")

    after = _valid_edges(conn)
    # a-b now weight 1 (only d2's chunk); c orphaned so a-c / b-c gone.
    assert after == [("a", "b", 1)]

    # Equals a from-scratch projection over the remaining active entities.
    active = [r["id"] for r in conn.execute("SELECT id FROM entities WHERE invalid_at IS NULL")]
    conn.execute("DELETE FROM relationships WHERE type='co_occurs' AND invalid_at IS NULL")
    recompute_cooccurrence(conn, active); conn.commit()
    assert _valid_edges(conn) == after

    # c is gone (hard-deleted orphan).
    assert conn.execute("SELECT COUNT(*) n FROM entities WHERE id='c'").fetchone()["n"] == 0
    store.close()
