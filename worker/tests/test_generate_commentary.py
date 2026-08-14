from src.db import get_connection
from src.jobs.generate_commentary import _clean_payload, _select_nodes, POSE_NAMES


def test_clean_payload_snaps_invalid_pose():
    raw = {"comments": [
        {"kind": "description", "text": "A.", "pose": "bogus"},
        {"kind": "omnissiah", "text": "B.", "pose": "galxy"},
        {"kind": "humor", "text": "C.", "pose": ""},
    ]}
    out = _clean_payload(raw)
    assert len(out) == 3
    assert out[0]["pose"] == "reading"    # description default
    assert out[1]["pose"] == "galxy"      # valid, kept
    assert out[2]["pose"] == "pointing"   # humor default
    assert all(c["pose"] in POSE_NAMES for c in out)


def test_clean_payload_rejects_duplicate_kinds():
    # three "description" → a missing kind → reject (not persisted)
    assert _clean_payload({"comments": [
        {"kind": "description", "text": "a", "pose": "reading"},
        {"kind": "description", "text": "b", "pose": "reading"},
        {"kind": "description", "text": "c", "pose": "reading"},
    ]}) is None


def test_clean_payload_reorders_to_canonical():
    out = _clean_payload({"comments": [
        {"kind": "humor", "text": "h", "pose": "pointing"},
        {"kind": "description", "text": "d", "pose": "reading"},
        {"kind": "omnissiah", "text": "o", "pose": "galxy"},
    ]})
    assert [c["kind"] for c in out] == ["description", "omnissiah", "humor"]


def test_clean_payload_rejects_incomplete():
    assert _clean_payload({"comments": []}) is None
    assert _clean_payload({"comments": [{"kind": "description", "text": "x", "pose": "reading"}]}) is None
    assert _clean_payload({}) is None
    assert _clean_payload({"comments": [
        {"kind": "description", "text": "  ", "pose": "reading"},
        {"kind": "omnissiah", "text": "b", "pose": "galxy"},
        {"kind": "humor", "text": "c", "pose": "pointing"},
    ]}) is None  # empty text → reject


def _seed(conn):
    conn.execute("INSERT INTO collections (id, name, path, root_path, document_count) VALUES (?,?,?,?,?)",
                 ("r1", "tracker", "tracker", "/x", 5))
    conn.execute("INSERT INTO domains (id, path, parent_path, document_count) VALUES (?,?,?,?)",
                 ("d1", "software/tools", "software", 3))
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?,?,?)",
                 ("e1", "widget", "capability"))
    conn.execute("INSERT INTO documents (id, title, content, content_hash) VALUES (?,?,?,?)",
                 ("doc1", "d", "text", "h1"))
    conn.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES (?,?)", ("e1", "doc1"))
    conn.commit()


def test_select_nodes_and_only_missing(test_db):
    conn = get_connection(test_db)
    _seed(conn)

    assert [n[1] for n in _select_nodes(conn, "collection", 10, only_missing=True)] == ["r1"]
    assert [n[1] for n in _select_nodes(conn, "domain", 10, only_missing=True)] == ["software/tools"]
    ents = _select_nodes(conn, "entity", 10, only_missing=True)
    assert [n[1] for n in ents] == ["e1"] and ents[0][2] == "widget"

    # once commentary exists, only_missing must exclude it
    conn.execute("INSERT INTO node_commentary (node_type, node_id, comments_json, model, source_hash) "
                 "VALUES ('entity','e1','[]','m','h')")
    conn.commit()
    assert _select_nodes(conn, "entity", 10, only_missing=True) == []
    assert [n[1] for n in _select_nodes(conn, "entity", 10, only_missing=False)] == ["e1"]
    conn.close()


def test_select_nodes_skips_empty_domains(test_db):
    """An empty domain (document_count=0) has no context and would spend an LLM call from
    the bounded budget — the collection path already filters these, so domains must too."""
    conn = get_connection(test_db)
    conn.execute("INSERT INTO domains (id, path, parent_path, document_count) VALUES ('d0','empty/leaf','empty',0)")
    conn.execute("INSERT INTO domains (id, path, parent_path, document_count) VALUES ('d2','has/docs','has',4)")
    conn.commit()
    paths = [n[1] for n in _select_nodes(conn, "domain", 10, only_missing=False)]
    assert "empty/leaf" not in paths, "a document_count=0 domain was selected"
    assert "has/docs" in paths
    conn.close()
