"""The tables the graph read layer is built on.

Nothing reads these yet — they land ahead of the code so the two move in separate
revertible steps. What is worth pinning now is the part that is expensive to discover
later: the constraints, because adding them after rows exist requires a table rebuild,
and the indexes, because their absence is invisible until a graph is large enough to
be slow.
"""

import sqlite3

import pytest

import src.db as db

_NEW_TABLES = ["graph_snapshot", "domain_edges", "collections",
               "document_collections", "collection_edges"]


@pytest.fixture
def fresh_db(tmp_path):
    p = str(tmp_path / "fresh.db")
    db.init_db(p)
    return p


def test_every_table_is_created(fresh_db):
    conn = db.get_connection(fresh_db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(_NEW_TABLES) <= tables


def test_the_indexes_the_read_layer_depends_on_exist(fresh_db):
    """Both exist because their absence is a silent performance cliff, not an error.

    `entity_sources` has no primary key, so without its index the per-entity
    source_count and the trade-route self-joins scan the whole table.
    `document_domains` has only a composite PK, which cannot be seeked by path, so
    every domain-scoped read scans as well.
    """
    conn = db.get_connection(fresh_db)
    idx = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_entity_sources_entity", "idx_document_domains_path",
            "idx_document_collections_collection"} <= idx


def test_composite_keys_reject_nulls(fresh_db):
    """SQLite does NOT imply NOT NULL from a composite PRIMARY KEY, unlike the SQL
    standard. Without the explicit constraint, NULL components slip past the key and
    duplicate the same logical row — and the constraint cannot be added later without
    rebuilding the table."""
    conn = db.get_connection(fresh_db)
    conn.execute("INSERT INTO collections (id, name, path) VALUES ('c1', 'c1', 'c1')")

    for sql in [
        "INSERT INTO domain_edges (source, target, weight) VALUES (NULL, 'b', 1.0)",
        "INSERT INTO domain_edges (source, target, weight) VALUES ('a', NULL, 1.0)",
        "INSERT INTO document_collections (document_id, collection_id) VALUES (NULL, 'c1')",
        "INSERT INTO collection_edges (source, target, type) VALUES ('c1', 'c1', NULL)",
    ]:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)


def test_the_snapshot_row_is_seeded_dirty(fresh_db):
    """Seeded so a writer can flag a rebuild with a plain UPDATE before the first build
    has ever run — no writer should have to know whether a snapshot exists yet."""
    conn = db.get_connection(fresh_db)
    row = conn.execute("SELECT id, dirty, payload FROM graph_snapshot").fetchone()
    assert row["id"] == "current"
    assert row["dirty"] == 1
    assert row["payload"] is None


def test_mark_graph_dirty_is_safe_before_any_build(fresh_db):
    conn = db.get_connection(fresh_db)
    conn.execute("UPDATE graph_snapshot SET dirty = 0 WHERE id = 'current'")
    db.mark_graph_dirty(conn)
    assert conn.execute("SELECT dirty FROM graph_snapshot").fetchone()[0] == 1


def test_a_collection_edge_pair_can_carry_two_types(fresh_db):
    """`type` is part of the key on purpose: two collections can be related in more
    than one way at once (a declared dependency AND a trajectory), and collapsing them
    would silently drop one."""
    conn = db.get_connection(fresh_db)
    conn.executemany("INSERT INTO collections (id, name, path) VALUES (?, ?, ?)",
                     [("a", "a", "a"), ("b", "b", "b")])
    conn.execute("INSERT INTO collection_edges (source, target, type, weight) "
                 "VALUES ('a', 'b', 'uses', 1.0)")
    conn.execute("INSERT INTO collection_edges (source, target, type, weight) "
                 "VALUES ('a', 'b', 'chain_next', 1.0)")
    assert conn.execute("SELECT COUNT(*) FROM collection_edges").fetchone()[0] == 2

    with pytest.raises(sqlite3.IntegrityError):  # ...but the same type twice is not
        conn.execute("INSERT INTO collection_edges (source, target, type, weight) "
                     "VALUES ('a', 'b', 'uses', 2.0)")


def test_init_db_is_idempotent(fresh_db):
    """It runs on every open, so a second pass must not disturb what the first built."""
    conn = db.get_connection(fresh_db)
    conn.execute("INSERT INTO collections (id, name, path) VALUES ('keep', 'keep', 'keep')")
    conn.commit()

    db.reset_initialized(fresh_db)
    db.init_db(fresh_db)

    conn = db.get_connection(fresh_db)
    assert conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0] == 1
    assert conn.execute("SELECT dirty FROM graph_snapshot").fetchone()[0] == 1


def test_connections_are_configured_by_one_factory(fresh_db):
    """init_db takes its connection from get_connection rather than repeating the
    PRAGMAs, so WAL and busy_timeout have a single definition."""
    conn = db.get_connection(fresh_db)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0
