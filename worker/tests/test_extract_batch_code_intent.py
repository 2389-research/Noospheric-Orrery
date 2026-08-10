# ABOUTME: Tests for extract_batch's code_intent scope — Phase 2 processing of
# ABOUTME: Phase 1 repo/module/file intent docs, with co-occurrence gated to file level.

import json
import uuid
from types import SimpleNamespace

from src.db import get_connection


def _fake_relay_complete(model, max_tokens, messages):
    """Return a fixed extraction result keyed off which chunk text was sent."""
    content = messages[0]["content"]
    if "FILE_CHUNK_TEXT" in content:
        entities = [{"name": "alpha", "type": "Thing"}, {"name": "beta", "type": "Thing"}]
    else:
        entities = [{"name": "gamma", "type": "Thing"}, {"name": "delta", "type": "Thing"}]
    return SimpleNamespace(text=json.dumps({"entities": entities}))


class FakeRelay:
    """Stand-in for orrery_relay.Relay — no Bedrock/gateway calls."""

    @classmethod
    def from_settings(cls, settings, **overrides):
        return cls()

    async def complete(self, model, max_tokens, messages, **kwargs):
        return _fake_relay_complete(model, max_tokens, messages)


async def test_run_extract_batch_code_intent_scope_gates_cooccurrence_on_the_flag(
    tmp_path, monkeypatch
):
    """Co-occurrence is gated by `emits_cooccurrence`, not by a structural label.

    This used to read `level != 'file'`, which meant every collection kind had to
    impersonate a code repo to opt in — tracker-run ingestion labelled a *spec* a
    "file" for exactly that reason. The default per role is unchanged (only leaves
    emit), but it is now stated on the row rather than inferred.
    """
    db_path = str(tmp_path / "test.db")
    from src.db import init_db

    init_db(db_path)

    collection_id = str(uuid.uuid4())
    spec_id = "spec1"
    file_doc_id = str(uuid.uuid4())
    module_doc_id = str(uuid.uuid4())

    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO collections (id, name, path, root_path) VALUES (?, ?, ?, ?)",
        (collection_id, "demo-repo", "demo-repo", str(tmp_path)),
    )
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, ?)",
        (spec_id, "Extract entities from this code intent doc."),
    )

    # Leaf code_intent doc — co-occurrence SHOULD be written.
    conn.execute(
        "INSERT INTO documents (id, content, status, content_type) VALUES (?, ?, 'classified', 'code_intent')",
        (file_doc_id, "intent for a file"),
    )
    file_chunk_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) VALUES (?, ?, 0, 0, ?, ?)",
        (file_chunk_id, file_doc_id, len("FILE_CHUNK_TEXT: hello"), "FILE_CHUNK_TEXT: hello"),
    )
    conn.execute(
        "INSERT INTO document_collections (document_id, collection_id, parent_path, role, emits_cooccurrence) "
        "VALUES (?, ?, ?, 'leaf', 1)",
        (file_doc_id, collection_id, "demo-repo/a.py"),
    )

    # Group (module) code_intent doc — co-occurrence must NOT be written: a group
    # summary mentions everything beneath it, so its co-occurrence would be noise.
    conn.execute(
        "INSERT INTO documents (id, content, status, content_type) VALUES (?, ?, 'classified', 'code_intent')",
        (module_doc_id, "intent for a module"),
    )
    module_chunk_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) VALUES (?, ?, 0, 0, ?, ?)",
        (module_chunk_id, module_doc_id, len("MODULE_CHUNK_TEXT: hello"), "MODULE_CHUNK_TEXT: hello"),
    )
    conn.execute(
        "INSERT INTO document_collections (document_id, collection_id, parent_path, role, emits_cooccurrence) "
        "VALUES (?, ?, ?, 'group', 0)",
        (module_doc_id, collection_id, "demo-repo/mod"),
    )
    conn.commit()
    conn.close()

    import src.jobs.extract_batch as extract_batch_mod

    monkeypatch.setattr(extract_batch_mod, "Relay", FakeRelay)

    from src.jobs.extract_batch import run_extract_batch

    job = {
        "id": str(uuid.uuid4()),
        "config": json.dumps({"spec_id": spec_id, "scope": "code_intent"}),
    }

    await run_extract_batch(job, db_path)

    conn = get_connection(db_path)

    # Entities were created and sourced for BOTH docs.
    file_entity_rows = conn.execute(
        "SELECT entity_id FROM entity_sources WHERE document_id = ?", (file_doc_id,)
    ).fetchall()
    module_entity_rows = conn.execute(
        "SELECT entity_id FROM entity_sources WHERE document_id = ?", (module_doc_id,)
    ).fetchall()
    assert len(file_entity_rows) >= 2
    assert len(module_entity_rows) >= 2

    file_entity_ids = {r["entity_id"] for r in file_entity_rows}
    module_entity_ids = {r["entity_id"] for r in module_entity_rows}

    # Co-occurrence edges exist for the file-level doc's entities.
    rels = conn.execute(
        "SELECT from_entity, to_entity FROM relationships WHERE type = 'co_occurs'"
    ).fetchall()
    assert len(rels) >= 1
    for r in rels:
        assert r["from_entity"] in file_entity_ids
        assert r["to_entity"] in file_entity_ids

    # No co-occurrence edge involves the group doc's entities.
    for r in rels:
        assert r["from_entity"] not in module_entity_ids
        assert r["to_entity"] not in module_entity_ids

    conn.close()


async def test_a_non_leaf_can_opt_into_cooccurrence(tmp_path, monkeypatch):
    """The point of splitting the column: role and extraction behaviour are independent.

    Under the old guard this case was unreachable — the ONLY way to emit co-occurrence
    was to claim `level == 'file'`, so a tracker run had to call its spec a file. Here a
    document is structurally a `group` and still emits, which proves the two are no
    longer welded together.
    """
    db_path = str(tmp_path / "test.db")
    from src.db import init_db

    init_db(db_path)
    collection_id, spec_id, doc_id = str(uuid.uuid4()), "spec1", str(uuid.uuid4())

    conn = get_connection(db_path)
    conn.execute("INSERT INTO collections (id, name, path, root_path) VALUES (?, ?, ?, ?)",
                 (collection_id, "demo-repo", "demo-repo", str(tmp_path)))
    conn.execute("INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, ?)",
                 (spec_id, "Extract entities from this code intent doc."))
    conn.execute("INSERT INTO documents (id, content, status, content_type) "
                 "VALUES (?, ?, 'classified', 'code_intent')", (doc_id, "intent for a group"))
    conn.execute("INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) "
                 "VALUES (?, ?, 0, 0, ?, ?)",
                 (str(uuid.uuid4()), doc_id, len("GROUP_CHUNK_TEXT: hello"), "GROUP_CHUNK_TEXT: hello"))
    conn.execute("INSERT INTO document_collections (document_id, collection_id, parent_path, role, "
                 "emits_cooccurrence) VALUES (?, ?, '.', 'group', 1)", (doc_id, collection_id))
    conn.commit()
    conn.close()

    import src.jobs.extract_batch as extract_batch_mod
    monkeypatch.setattr(extract_batch_mod, "Relay", FakeRelay)
    from src.jobs.extract_batch import run_extract_batch

    await run_extract_batch(
        {"id": str(uuid.uuid4()),
         "config": json.dumps({"spec_id": spec_id, "scope": "code_intent"})}, db_path)

    conn = get_connection(db_path)
    rels = conn.execute("SELECT COUNT(*) FROM relationships WHERE type = 'co_occurs'").fetchone()[0]
    conn.close()
    assert rels >= 1, "a group that sets emits_cooccurrence=1 must still produce edges"
