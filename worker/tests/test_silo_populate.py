# ABOUTME: documents.silo_id population at ingest — precedence source_id > collection_id > None.
# ABOUTME: Mirrors test_upsert_document.py's FakeRelay + tmp-DB pattern.

import json
from types import SimpleNamespace

import pytest

from src.db import init_db, get_connection
from src.config import get_settings


class FakeRelay:
    """complete() -> entities keyed on chunk text; complete_structured() -> a domain."""

    @classmethod
    def from_settings(cls, settings, **overrides):
        return cls()

    async def complete(self, model, max_tokens, messages, **kwargs):
        return SimpleNamespace(text=json.dumps({"entities": [{"name": "alpha", "type": "Thing"}]}))

    async def complete_structured(self, model, max_tokens, messages, schema=None,
                                  tool_name=None, tool_description=None,
                                  ollama_options=None, **kwargs):
        return {"primary_domain": "techniques/test", "secondary_domains": [],
                "new_domains": [], "confidence": 0.9}


async def _upsert(conn, **kw):
    from src.jobs.upsert_document import upsert_document
    return await upsert_document(conn, FakeRelay(), get_settings(), **kw)


def _silo_id(conn, doc_id):
    return conn.execute("SELECT silo_id FROM documents WHERE id = ?", (doc_id,)).fetchone()["silo_id"]


@pytest.mark.asyncio
async def test_source_id_only_sets_silo_id(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    r = await _upsert(conn, source_path="/v/note.md", title="Note",
                      content="a note about ALPHA topics", source_id="v1")
    assert _silo_id(conn, r["document_id"]) == "v1"


@pytest.mark.asyncio
async def test_source_id_wins_over_collection_id(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    conn.execute("INSERT INTO collections (id, name, path) VALUES ('col1', 'Repo', '/r')")
    conn.commit()
    r = await _upsert(conn, source_path="/r/file.py", title="file.py",
                      content="a note about ALPHA topics", source_id="v1",
                      collection_id="col1", role="leaf", classify=False,
                      domain_path="software/repo")
    assert _silo_id(conn, r["document_id"]) == "v1"


@pytest.mark.asyncio
async def test_loose_upload_has_null_silo_id(tmp_path):
    db = str(tmp_path / "t.db"); init_db(db); conn = get_connection(db)
    r = await _upsert(conn, source_path="/v/loose.md", title="Loose",
                      content="a note about ALPHA topics")
    assert _silo_id(conn, r["document_id"]) is None
