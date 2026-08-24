# ABOUTME: run_extract_batch_image's inline canonical-entity fuse (~L117) scopes its
# ABOUTME: lookup by the image document's silo_id (#50), mirroring test_silo_scope_inline.

import json
import uuid

import pytest

from src.db import init_db, get_connection
from src.jobs import extract_batch_image


class FakeRelay:
    """complete_structured() always returns the SAME image entity, regardless of doc."""

    @classmethod
    def from_settings(cls, settings, **overrides):
        return cls()

    async def complete_structured(self, model, max_tokens, messages, schema=None,
                                  tool_name=None, tool_description=None, **kwargs):
        return {
            "entities": [{"name": "widget", "type": "Object"}],
            "description": "a widget",
            "tags": [],
        }


def _make_image_doc(conn, tmp_path, silo_id):
    doc_id = str(uuid.uuid4())
    img_path = tmp_path / f"{doc_id}.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    conn.execute(
        "INSERT INTO documents (id, title, content, content_hash, source_path, "
        "content_type, status, silo_id) VALUES (?, 'T', '', 'h', ?, 'image', 'classified', ?)",
        (doc_id, str(img_path), silo_id))
    conn.commit()
    return doc_id


def _make_spec(conn):
    spec_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, 'general', 1, 'extract things')",
        (spec_id,))
    conn.commit()
    return spec_id


def _entity_count(conn):
    return conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]


async def _run_batch(db_path, spec_id, monkeypatch):
    monkeypatch.setattr(extract_batch_image, "Relay", FakeRelay)
    job = {"id": str(uuid.uuid4()), "config": json.dumps({"spec_id": spec_id, "scope": "all_images"})}
    await extract_batch_image.run_extract_batch_image(job, db_path)


@pytest.mark.asyncio
async def test_same_name_in_different_silos_stays_distinct(tmp_path, monkeypatch):
    # Both docs land in ONE batch run (never-before-extracted), so each is processed
    # exactly once — this isolates the silo scoping from the batch job's separate
    # (pre-existing) behavior of reprocessing already-`extracted` docs on a later run.
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    spec_id = _make_spec(conn)

    doc_a = _make_image_doc(conn, tmp_path, "A")
    doc_b = _make_image_doc(conn, tmp_path, "B")
    conn.close()
    await _run_batch(db, spec_id, monkeypatch)

    conn = get_connection(db)
    assert _entity_count(conn) == 2
    silos = {r["silo_id"] for r in conn.execute(
        "SELECT DISTINCT d.silo_id FROM entities e "
        "JOIN entity_sources es ON es.entity_id = e.id "
        "JOIN documents d ON d.id = es.document_id "
        "WHERE e.canonical_name = 'widget'")}
    assert silos == {"A", "B"}


@pytest.mark.asyncio
async def test_same_name_in_same_silo_merges(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    spec_id = _make_spec(conn)

    doc_a = _make_image_doc(conn, tmp_path, "A")
    doc_a2 = _make_image_doc(conn, tmp_path, "A")
    conn.close()
    await _run_batch(db, spec_id, monkeypatch)

    conn = get_connection(db)
    assert _entity_count(conn) == 1
    entity_id = conn.execute("SELECT id FROM entities WHERE canonical_name = 'widget'").fetchone()["id"]
    doc_ids = {r["document_id"] for r in conn.execute(
        "SELECT document_id FROM entity_sources WHERE entity_id = ?", (entity_id,))}
    assert doc_ids == {doc_a, doc_a2}
