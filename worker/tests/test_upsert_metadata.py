import json

import pytest

from src.db import init_db, get_connection
from src.config import get_settings
from src.jobs.upsert_document import upsert_document
from .test_upsert_document import FakeRelay


@pytest.mark.asyncio
async def test_metadata_persisted_on_create(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    conn = get_connection(db)
    await upsert_document(conn, FakeRelay(), get_settings(), source_path="/v/a.md",
                          title="a", content="body", classify=False,
                          metadata={"tags": ["x"], "title": "a"})
    row = conn.execute("SELECT metadata FROM documents WHERE source_path='/v/a.md'").fetchone()
    assert json.loads(row["metadata"])["tags"] == ["x"]


@pytest.mark.asyncio
async def test_metadata_updated_in_place(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    conn = get_connection(db)
    await upsert_document(conn, FakeRelay(), get_settings(), source_path="/v/a.md",
                          title="a", content="v1", classify=False, metadata={"v": 1})
    await upsert_document(conn, FakeRelay(), get_settings(), source_path="/v/a.md",
                          title="a", content="v2", classify=False, metadata={"v": 2})
    row = conn.execute("SELECT metadata FROM documents WHERE source_path='/v/a.md'").fetchone()
    assert json.loads(row["metadata"])["v"] == 2


@pytest.mark.asyncio
async def test_metadata_only_change_persists_on_skip(tmp_path):
    """Frontmatter-only edit: identical body (same content hash -> 'skipped'), but the
    title/metadata changed and MUST still persist (CodeRabbit #80). The content hash is
    over the cleaned body only, so without this a note whose only change was its
    frontmatter would silently keep stale title/metadata."""
    db = str(tmp_path / "t.db")
    init_db(db)
    conn = get_connection(db)
    r1 = await upsert_document(conn, FakeRelay(), get_settings(), source_path="/v/a.md",
                               title="old", content="unchanged body", classify=False,
                               metadata={"tags": ["draft"]})
    assert r1["action"] == "created"
    r2 = await upsert_document(conn, FakeRelay(), get_settings(), source_path="/v/a.md",
                               title="new", content="unchanged body", classify=False,
                               metadata={"tags": ["final"]})
    assert r2["action"] == "skipped"                          # body unchanged -> no re-extraction
    row = conn.execute(
        "SELECT title, metadata FROM documents WHERE source_path='/v/a.md'").fetchone()
    assert row["title"] == "new"                              # title change persisted despite skip
    assert json.loads(row["metadata"])["tags"] == ["final"]   # metadata change persisted
