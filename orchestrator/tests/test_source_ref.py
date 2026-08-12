# ABOUTME: /documents/{id} returns a resolvable git_ref for code docs (so an agent
# ABOUTME: can fetch the real source from GitHub); None for docs without provenance.
"""`source_path` is an absolute path inside the ingesting container, so it resolves
nowhere else — the limitation NOOSPHERE.md warns archive recipients about. `git_ref` is
the shareable counterpart: remote + commit + repo-relative path, and a blob URL.

It is all-or-nothing on purpose. A ref that looks valid but does not resolve is worse
than no ref, so anything that cannot be turned into a real GitHub location comes back
as None (or a None `path`) rather than a guess.
"""
import uuid


def _seed_repo_doc(store, remote_url, commit_sha, root_path, source_path,
                   content_type="code_intent", role="leaf"):
    """One collection + one document linked to it.

    NOTE the link columns: main's document_collections carries `role` +
    `emits_cooccurrence`, NOT the repo-era `level` the fork still has. Copying the
    fork's INSERT verbatim fails here with "no such column: level".
    """
    conn = store.conn
    collection_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO collections (id, name, path, root_path, remote_url, commit_sha) "
        "VALUES (?,?,?,?,?,?)",
        (collection_id, "tracker", root_path, root_path, remote_url, commit_sha),
    )
    doc_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO documents (id, title, content, content_hash, source_path, content_type, status) "
        "VALUES (?,?,?,?,?,?,'classified')",
        (doc_id, "engine.go", "summary", "hash-" + doc_id, source_path, content_type),
    )
    conn.execute(
        "INSERT INTO document_collections (document_id, collection_id, role, parent_path) "
        "VALUES (?,?,?,?)",
        (doc_id, collection_id, role, None),
    )
    conn.commit()
    return doc_id


def test_document_git_ref_for_code(test_store, test_client):
    doc_id = _seed_repo_doc(
        test_store,
        remote_url="github.com/2389-research/tracker",
        commit_sha="a" * 40,
        root_path="/data/repos/tracker",
        source_path="/data/repos/tracker/pipeline/engine.go",
    )
    ref = test_client.get(f"/documents/{doc_id}").json()["git_ref"]
    assert ref["remote"] == "github.com/2389-research/tracker"
    assert ref["commit"] == "a" * 40
    assert ref["path"] == "pipeline/engine.go"
    assert ref["url"] == "https://github.com/2389-research/tracker/blob/" + "a" * 40 + "/pipeline/engine.go"


def test_document_git_ref_none_without_provenance(test_store, test_client):
    """A repo ingested before provenance was captured — or, until PR #67, ANY repo
    ingested in Docker, where git refused the bind-mounted checkout as dubious
    ownership and `_git_coordinates` silently returned (None, None)."""
    doc_id = _seed_repo_doc(test_store, None, None, "/data/repos/x", "/data/repos/x/a.py")
    assert test_client.get(f"/documents/{doc_id}").json()["git_ref"] is None


def test_document_git_ref_none_for_non_code(test_store, test_client):
    """Linked to a repo WITH provenance, but not a code doc -> no ref."""
    doc_id = _seed_repo_doc(
        test_store, "github.com/2389-research/tracker", "b" * 40,
        "/data/repos/tracker", "/data/repos/tracker/notes.md", content_type="text",
    )
    assert test_client.get(f"/documents/{doc_id}").json()["git_ref"] is None


def test_a_repo_level_document_has_no_path_or_url(test_store, test_client):
    """The repo-level summary describes the whole checkout, so `relpath` yields "."
    and there is no file to link to. Remote and commit still identify the repo, but
    a blob URL ending in "/." would 404 — so `path` and `url` are omitted."""
    doc_id = _seed_repo_doc(
        test_store, "github.com/2389-research/tracker", "c" * 40,
        "/data/repos/tracker", "/data/repos/tracker", role="root",
    )
    ref = test_client.get(f"/documents/{doc_id}").json()["git_ref"]
    assert ref["remote"] == "github.com/2389-research/tracker"
    assert ref["path"] is None
    assert "url" not in ref


def test_a_source_path_outside_the_repo_root_yields_no_path(test_store, test_client):
    """A stale or mislinked `source_path` makes `relpath` climb out with "..".

    Publishing that as a repo-relative path produces a URL pointing at something the
    repo does not contain, which is the "looks valid but resolves wrong" failure this
    guard exists to prevent.
    """
    doc_id = _seed_repo_doc(
        test_store, "github.com/2389-research/tracker", "d" * 40,
        "/data/repos/tracker", "/data/repos/other-repo/secrets.env",
    )
    ref = test_client.get(f"/documents/{doc_id}").json()["git_ref"]
    assert ref["path"] is None, "a path escaping the repo root was published"
    assert "url" not in ref


def test_a_path_needing_escaping_is_quoted_but_keeps_separators(test_store, test_client):
    """Path separators must survive quoting or the URL collapses to one segment;
    everything else that would change the URL's meaning must not."""
    doc_id = _seed_repo_doc(
        test_store, "github.com/2389-research/tracker", "e" * 40,
        "/data/repos/tracker", "/data/repos/tracker/docs/my notes#1.md",
    )
    ref = test_client.get(f"/documents/{doc_id}").json()["git_ref"]
    assert ref["path"] == "docs/my notes#1.md"
    assert ref["url"].endswith("/docs/my%20notes%231.md")
    assert "/docs/" in ref["url"], "separators were escaped away"


def test_a_document_in_no_collection_has_no_ref(test_store, test_client):
    """An uploaded document was never part of a repo, so there is nothing to resolve."""
    conn = test_store.conn
    doc_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO documents (id, title, content, content_hash, content_type, status) "
        "VALUES (?,?,?,?,'code_intent','classified')",
        (doc_id, "orphan", "summary", "hash-" + doc_id),
    )
    conn.commit()
    assert test_client.get(f"/documents/{doc_id}").json()["git_ref"] is None
