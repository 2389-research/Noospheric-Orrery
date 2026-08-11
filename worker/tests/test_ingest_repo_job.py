# ABOUTME: Tests for the Phase 1 ingest_repo worker job — repo -> summarized
# ABOUTME: code_intent documents, domain assignment, and Phase 2 job enqueue.

import json
import uuid

from src.db import init_db, get_connection


def _make_fixture_repo(tmp_path):
    repo_dir = tmp_path / "demo-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Demo repo\nDoes cool stuff.")
    (repo_dir / "pyproject.toml").write_text(
        '[project]\nname = "demo-repo"\ndependencies = []\n'
    )
    mod_dir = repo_dir / "mod"
    mod_dir.mkdir()
    (mod_dir / "a.py").write_text("def hello():\n    return 'hi'\n")
    return repo_dir


async def test_run_ingest_repo_creates_intent_docs_and_enqueues_phase2(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    repo_dir = _make_fixture_repo(tmp_path)

    collection_id = str(uuid.uuid4())
    spec_id = str(uuid.uuid4())
    domain_path = "development/data-mining"
    secondary_domain = "development/tooling"

    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO collections (id, name, path, root_path) VALUES (?, ?, ?, ?)",
        (collection_id, "demo-repo", "demo-repo", str(repo_dir)),
    )
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, 'spec body')",
        (spec_id,),
    )
    conn.commit()
    conn.close()

    job = {
        "id": str(uuid.uuid4()),
        "type": "ingest_repo",
        "target": collection_id,
        "config": json.dumps(
            {
                "root_path": str(repo_dir),
                "collection_id": collection_id,
                "collection_name": "demo-repo",
                "spec_id": spec_id,
                "domain_path": domain_path,
            }
        ),
    }

    # Stub the summarizer so no Bedrock call happens.
    import src.jobs.ingest_repo as ingest_repo_mod

    def fake_make_summarize_fn(relay, model):
        def summarize_fn(level, *, path="", content="", root="", parent=None, files="", submods=""):
            return f"intent for {path}"

        return summarize_fn

    monkeypatch.setattr(ingest_repo_mod, "make_summarize_fn", fake_make_summarize_fn)

    # ingest_repo now classifies on the grounded repo summary — stub it (no Bedrock call).
    async def fake_classify(relay, title, excerpt, existing_taxonomy, model):
        return {"primary_domain": domain_path, "secondary_domains": [secondary_domain], "confidence": 0.9}

    monkeypatch.setattr(ingest_repo_mod, "classify_document", fake_classify)

    from src.jobs.ingest_repo import run_ingest_repo

    await run_ingest_repo(job, db_path)

    conn = get_connection(db_path)

    docs = conn.execute(
        "SELECT id, content, content_type FROM documents WHERE content_type = 'code_intent'"
    ).fetchall()
    # repo artifact + module artifact (mod) + file artifact (mod/a.py)
    # + 2 root-level file artifacts (README.md, pyproject.toml)
    assert len(docs) >= 3

    # role, not `level`: codesum still speaks repo/module/file (correct for a
    # filesystem), but ingest maps it onto the collection-neutral role at the seam and
    # leaves `level` NULL so db.py's backfill can tell legacy rows from new ones.
    roles_seen = set()
    emits = {}
    for doc in docs:
        doc_id, content = doc["id"], doc["content"]
        assert content.startswith("intent for ")

        chunk = conn.execute(
            "SELECT text, offset, length FROM chunks WHERE document_id = ?", (doc_id,)
        ).fetchone()
        assert chunk is not None
        assert chunk["text"] == content
        assert chunk["offset"] == 0
        assert chunk["length"] == len(content)

        dd = conn.execute(
            "SELECT is_primary, confidence FROM document_domains WHERE document_id = ? AND domain_path = ?",
            (doc_id, domain_path),
        ).fetchone()
        assert dd is not None
        assert dd["is_primary"] == 1
        assert dd["confidence"] == 0.9  # actual classifier confidence, not hard-coded 1.0

        sec = conn.execute(
            "SELECT is_primary FROM document_domains WHERE document_id = ? AND domain_path = ?",
            (doc_id, secondary_domain),
        ).fetchone()
        assert sec is not None and sec["is_primary"] == 0  # secondary facet persisted

        # There is no `level` column in this schema: `role` + `emits_cooccurrence` are
        # the whole contract, which is why the ingest seam maps codesum's
        # repo/module/file vocabulary onto role explicitly instead of persisting it.
        repo_row = conn.execute(
            "SELECT role, emits_cooccurrence FROM document_collections "
            "WHERE document_id = ? AND collection_id = ?",
            (doc_id, collection_id),
        ).fetchone()
        assert repo_row is not None
        roles_seen.add(repo_row["role"])
        emits.setdefault(repo_row["role"], set()).add(repo_row["emits_cooccurrence"])

    assert roles_seen == {"root", "group", "leaf"}
    # The co-occurrence switch is now stated per row rather than inferred from the
    # structural label. Only leaves carry meaningful entity locality — a group or root
    # summary mentions everything beneath it, so its co-occurrence would be noise.
    assert emits == {"root": {0}, "group": {0}, "leaf": {1}}

    domain_row = conn.execute(
        "SELECT document_count FROM domains WHERE path = ?", (domain_path,)
    ).fetchone()
    assert domain_row is not None
    assert domain_row["document_count"] == len(docs)
    assert domain_row["document_count"] > 0

    # Secondary domain is persisted with its own doc-count (same semantics as primary).
    sec_row = conn.execute(
        "SELECT document_count FROM domains WHERE path = ?", (secondary_domain,)
    ).fetchone()
    assert sec_row is not None
    assert sec_row["document_count"] == len(docs)

    extract_job = conn.execute(
        "SELECT config FROM jobs WHERE type = 'extract_batch'"
    ).fetchone()
    assert extract_job is not None
    extract_config = json.loads(extract_job["config"])
    assert extract_config["scope"] == "code_intent"
    assert extract_config["spec_id"] == spec_id

    conn.close()


async def test_run_ingest_repo_assigns_files_to_subdomains(tmp_path, monkeypatch):
    """When the classifier returns subdomains, each FILE is placed in its
    best-matching subdomain (is_primary=1) while module/repo docs keep the
    primary domain. Embedding is stubbed so no model loads."""
    import numpy as np
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    repo_dir = _make_fixture_repo(tmp_path)
    collection_id, spec_id = str(uuid.uuid4()), str(uuid.uuid4())
    main_domain = "software/ai-agents/llm-orchestration"
    subs = ["software/ai-agents/tool-use", "software/developer-tools/parser"]

    conn = get_connection(db_path)
    conn.execute("INSERT INTO collections (id, name, path, root_path) VALUES (?, ?, ?, ?)",
                 (collection_id, "demo-repo", "demo-repo", str(repo_dir)))
    conn.execute("INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, 'spec body')",
                 (spec_id,))
    conn.commit()
    conn.close()

    job = {"id": str(uuid.uuid4()), "type": "ingest_repo", "target": collection_id,
           "config": json.dumps({"root_path": str(repo_dir), "collection_id": collection_id,
                                 "collection_name": "demo-repo", "spec_id": spec_id})}

    import src.jobs.ingest_repo as ingest_repo_mod

    def fake_make_summarize_fn(relay, model):
        def summarize_fn(level, *, path="", content="", root="", parent=None, files="", submods=""):
            return f"intent for {path}"
        return summarize_fn
    monkeypatch.setattr(ingest_repo_mod, "make_summarize_fn", fake_make_summarize_fn)

    async def fake_classify(relay, title, excerpt, existing_taxonomy, model):
        return {"primary_domain": main_domain, "secondary_domains": [], "subdomains": subs, "confidence": 0.9}
    monkeypatch.setattr(ingest_repo_mod, "classify_document", fake_classify)

    # Stub the embedder: equal vectors → argmax picks subdomain[0] for every file.
    monkeypatch.setattr("src.normalizer.embed_entities",
                        lambda texts: np.ones((len(texts), 8), dtype=np.float32))

    from src.jobs.ingest_repo import run_ingest_repo
    await run_ingest_repo(job, db_path)

    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT dc.role, dd.domain_path FROM document_domains dd "
        "JOIN document_collections dc ON dc.document_id = dd.document_id "
        "WHERE dd.is_primary = 1").fetchall()
    by_role = {}
    for r in rows:
        by_role.setdefault(r["role"], set()).add(r["domain_path"])
    # every LEAF landed in the (stub-chosen) subdomain, NOT the repo's primary
    assert by_role.get("leaf") == {subs[0]}
    # group/root docs keep the primary domain
    assert by_role.get("group") == {main_domain}
    assert by_role.get("root") == {main_domain}
    conn.close()
