# ABOUTME: Unit tests for the identity-noise filter + its wiring into extract_batch.
# ABOUTME: Entities that are just a file path or the file/module/repo's own name are dropped.

import json
import uuid
from types import SimpleNamespace

import pytest

from src.db import get_connection, init_db
from src.identity_filter import is_identity_noise


# --- unit: the pure filter -------------------------------------------------

def test_file_extension_names_are_noise():
    assert is_identity_noise("traverse.py")
    assert is_identity_noise("Cargo.toml")
    assert is_identity_noise("README.md")


def test_collection_and_file_self_names_are_noise():
    assert is_identity_noise("demo-repo", collection_name="demo-repo")
    assert is_identity_noise("a.py", doc_path="src/pkg/a.py")     # basename of the doc path
    assert is_identity_noise("src/pkg/a.py", doc_path="src/pkg/a.py")  # full path


@pytest.mark.parametrize("spelling", ["demo-repo", "demo_repo", "demo repo"])
@pytest.mark.parametrize("configured", ["demo-repo", "demo_repo", "demo repo"])
def test_every_separator_spelling_matches_every_other(spelling, configured):
    """A model writes the separator however it likes, so all forms are one identity.

    Cross-producted deliberately: the variants used to be derived from the input
    directly, so whether `demo repo` was caught depended on whether the collection's
    own name happened to contain a hyphen — the same entity was filtered in one repo
    and not in the next.
    """
    assert is_identity_noise(spelling, collection_name=configured)


def test_the_module_stem_is_noise_not_just_the_filename():
    """A summary of `traverse.py` names the unit `traverse` about as often.

    Same hub problem as the filename: it co-occurs with everything in its own document
    by construction.
    """
    assert is_identity_noise("traverse", doc_path="src/traverse.py")
    assert is_identity_noise("steal", doc_path="src/executor/steal.py")


def test_the_stem_rule_only_strips_known_source_extensions():
    """A dot does not make a suffix an extension.

    Blind rpartition-on-dot would treat the tail of any dotted filename as an
    extension and blacklist whatever precedes it, so a path like `metrics.2026.csv`
    would quietly filter the concept `metrics.2026`. Only extensions in SOURCE_EXTS
    are stripped.
    """
    assert not is_identity_noise("metrics", doc_path="data/metrics.csv")
    assert not is_identity_noise("backup", doc_path="tmp/backup.bak")
    # A *known* extension is stripped, including on a multi-dot name — `notes.2026`
    # really is the stem of `notes.2026.md`, and it is identity for that document.
    assert is_identity_noise("notes.2026", doc_path="docs/notes.2026.md")
    # The basename and the full path are identity regardless of extension — it is only
    # the STEM stripping that SOURCE_EXTS gates.
    assert is_identity_noise("metrics.csv", doc_path="data/metrics.csv")
    assert is_identity_noise("data/metrics.csv", doc_path="data/metrics.csv")


def test_real_concepts_survive():
    assert not is_identity_noise("dependency graph", doc_path="src/pkg/a.py", collection_name="demo-repo")
    assert not is_identity_noise("recursive summarization", collection_name="demo-repo")
    # A stem is only identity for its OWN document — elsewhere it is a normal concept,
    # which is what keeps a genuinely important name in the graph.
    assert not is_identity_noise("traverse", doc_path="src/other.py")
    assert is_identity_noise("")  # empty IS noise


# --- wiring: extract_batch drops identity-noise entities -------------------

def _fake_relay_complete(model, max_tokens, messages):
    # Two identity-noise names (a filename and the repo name) + one real concept.
    entities = [
        {"name": "a.py", "type": "Thing"},
        {"name": "demo-repo", "type": "Thing"},
        {"name": "recursive summarization", "type": "capability"},
    ]
    return SimpleNamespace(text=json.dumps({"entities": entities}))


class FakeRelay:
    @classmethod
    def from_settings(cls, settings, **overrides):
        return cls()

    async def complete(self, model, max_tokens, messages, **kwargs):
        return _fake_relay_complete(model, max_tokens, messages)


async def test_extract_batch_filters_identity_noise(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    collection_id = str(uuid.uuid4())
    spec_id = "spec1"
    doc_id = str(uuid.uuid4())

    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO collections (id, name, path, root_path) VALUES (?, ?, ?, ?)",
        (collection_id, "demo-repo", "demo-repo", str(tmp_path)),
    )
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, ?)",
        (spec_id, "Extract entities from this code intent doc."),
    )
    # Leaf doc; its title is the collection-relative path (as repo ingest stores it),
    # which is what makes the title usable as identity context.
    conn.execute(
        "INSERT INTO documents (id, title, content, status, content_type) "
        "VALUES (?, ?, ?, 'classified', 'code_intent')",
        (doc_id, "a.py", "intent for a file"),
    )
    chunk_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) "
        "VALUES (?, ?, 0, 0, ?, ?)",
        (chunk_id, doc_id, len("FILE_CHUNK_TEXT"), "FILE_CHUNK_TEXT"),
    )
    conn.execute(
        "INSERT INTO document_collections (document_id, collection_id, parent_path, role, "
        "emits_cooccurrence) VALUES (?, ?, ?, 'leaf', 1)",
        (doc_id, collection_id, "demo-repo"),
    )
    conn.commit()
    conn.close()

    import src.jobs.extract_batch as extract_batch_mod

    monkeypatch.setattr(extract_batch_mod, "Relay", FakeRelay)

    from src.jobs.extract_batch import run_extract_batch

    job = {"id": str(uuid.uuid4()), "config": json.dumps({"spec_id": spec_id, "scope": "code_intent"})}
    await run_extract_batch(job, db_path)

    conn = get_connection(db_path)
    names = {r["canonical_name"] for r in conn.execute("SELECT canonical_name FROM entities").fetchall()}
    conn.close()

    assert "recursive summarization" in names  # the real concept survives
    assert "a.py" not in names                 # filename dropped
    assert "demo-repo" not in names            # repo name dropped
