# ABOUTME: extract_document_entities (the inline dedup at extraction time) scopes
# ABOUTME: its merge_map + canonical-name lookups by the document's silo_id (#50).

import json
import uuid
from types import SimpleNamespace

import pytest

from src.db import init_db, get_connection
from src.config import get_settings
from src.jobs.upsert_document import extract_document_entities


class FakeRelay:
    """complete() always returns the SAME entity name+type, regardless of doc."""

    async def complete(self, model, max_tokens, messages, **kwargs):
        return SimpleNamespace(text=json.dumps({"entities": [{"name": "widget", "type": "Thing"}]}))


def _make_doc(conn, silo_id):
    doc_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO documents (id, title, content, content_hash, source_path, status, silo_id) "
        "VALUES (?, 'T', 'c', 'h', ?, 'pending', ?)",
        (doc_id, f"/x/{doc_id}", silo_id))
    conn.commit()
    return doc_id


async def _extract(conn, doc_id):
    return await extract_document_entities(
        conn, FakeRelay(), get_settings(), doc_id=doc_id,
        chunks=[(str(uuid.uuid4()), "some chunk text")], spec="extract things",
        spec_version=0, scope="general", job_id=None, doc_path="x", collection_name="")


def _entity_count(conn):
    return conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]


@pytest.mark.asyncio
async def test_same_name_in_different_silos_stays_distinct(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)

    doc_a = _make_doc(conn, "A")
    doc_b = _make_doc(conn, "B")

    await _extract(conn, doc_a)
    await _extract(conn, doc_b)

    assert _entity_count(conn) == 2
    silos = {r["silo_id"] for r in conn.execute(
        "SELECT DISTINCT d.silo_id FROM entities e "
        "JOIN entity_sources es ON es.entity_id = e.id "
        "JOIN documents d ON d.id = es.document_id "
        "WHERE e.canonical_name = 'widget'")}
    assert silos == {"A", "B"}


@pytest.mark.asyncio
async def test_same_name_in_same_silo_merges(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)

    doc_a = _make_doc(conn, "A")
    doc_a2 = _make_doc(conn, "A")

    await _extract(conn, doc_a)
    await _extract(conn, doc_a2)

    assert _entity_count(conn) == 1
    entity_id = conn.execute("SELECT id FROM entities WHERE canonical_name = 'widget'").fetchone()["id"]
    doc_ids = {r["document_id"] for r in conn.execute(
        "SELECT document_id FROM entity_sources WHERE entity_id = ?", (entity_id,))}
    assert doc_ids == {doc_a, doc_a2}


@pytest.mark.asyncio
async def test_null_silo_docs_still_merge_among_themselves(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)

    doc_1 = _make_doc(conn, None)
    doc_2 = _make_doc(conn, None)

    await _extract(conn, doc_1)
    await _extract(conn, doc_2)

    assert _entity_count(conn) == 1
