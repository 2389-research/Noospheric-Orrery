# ABOUTME: Tests for the ingest_tracker_runs worker job — pre-made run summaries
# ABOUTME: -> one repo per run, chain edges, code_intent docs, Phase 2 enqueue.

import json
import uuid

import pytest

from src.db import init_db, get_connection


def _write_run(out_dir, runs_dir, label, rung, nodes=("Stage", "Build")):
    """Write one run's summary JSON + its staged raw artifacts."""
    (out_dir / f"{label}.json").write_text(json.dumps({
        "run_label": label,
        "rung": rung,
        "rollup": f"{label} overview: rung {rung}",
        "spec": {"text": f"{label} spec body", "artifacts": ["SPEC.md"]},
        "dip": {"recognized": f"{label} dip: gate-retry-escalate"},
        "nodes": [{"node": n, "summary": f"{label}/{n} did work"} for n in nodes],
    }))
    staged = runs_dir / label
    staged.mkdir(parents=True)
    (staged / "workflow.dip").write_text(f"workflow {label} {{}}\n")
    (staged / "spec.md").write_text(f"# {label} spec\n")


def _make_fixture_bundle(tmp_path):
    """A staged bundle: out/ (summaries + index) alongside runs/ (raw artifacts)."""
    bundle = tmp_path / "tracker-ingest"
    out_dir, runs_dir = bundle / "out", bundle / "runs"
    out_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)
    _write_run(out_dir, runs_dir, "run1", "R5")
    _write_run(out_dir, runs_dir, "run2", "R0")
    (out_dir / "index.json").write_text(json.dumps([
        {"run_label": "run1"}, {"run_label": "run2"},
    ]))
    return out_dir, runs_dir


def _seed_job(db_path, out_dir, runs_dir, spec_id, chain=None):
    """Insert the spec + the queued ingest job row (as the route would), and return
    the job dict the worker is handed."""
    job = {
        "id": str(uuid.uuid4()),
        "type": "ingest_tracker_runs",
        "target": "tracker-runs",
        "config": json.dumps({
            "out_dir": str(out_dir),
            "runs_dir": str(runs_dir),
            "spec_id": spec_id,
            "chain": chain,
        }),
    }
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, 'spec body')",
        (spec_id,),
    )
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, ?, ?, 'running', ?)",
        (job["id"], job["type"], job["target"], job["config"]),
    )
    conn.commit()
    conn.close()
    return job


def _stub_classify(monkeypatch, domain_path):
    import src.jobs.ingest_tracker_runs as mod

    async def fake_classify(relay, title, excerpt, existing_taxonomy, model):
        # The spec text is what the run gets classified on — assert it reached here.
        assert "spec body" in excerpt
        return {"primary_domain": domain_path, "secondary_domains": [], "confidence": 0.9}

    monkeypatch.setattr(mod, "classify_document", fake_classify)


async def test_ingest_tracker_runs_creates_repos_docs_and_enqueues_phase2(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    out_dir, runs_dir = _make_fixture_bundle(tmp_path)
    spec_id = str(uuid.uuid4())
    domain_path = "development/agent-orchestration"

    job = _seed_job(db_path, out_dir, runs_dir, spec_id)
    _stub_classify(monkeypatch, domain_path)

    from src.jobs.ingest_tracker_runs import run_ingest_tracker_runs
    await run_ingest_tracker_runs(job, db_path)

    conn = get_connection(db_path)

    # One repo per run, rooted at its staged artifact dir.
    repos = {r["name"]: r for r in conn.execute("SELECT name, root_path, document_count FROM collections").fetchall()}
    assert set(repos) == {"run1", "run2"}
    assert repos["run1"]["root_path"] == str(runs_dir / "run1")

    # Each run yields: overview (the collection ROOT) + spec + dip + one doc per node.
    docs = conn.execute(
        "SELECT d.id, d.title, d.source_path, dc.role, dc.parent_path, "
        "dc.emits_cooccurrence, dc.collection_id "
        "FROM documents d JOIN document_collections dc ON dc.document_id = d.id "
        "WHERE d.content_type = 'code_intent'"
    ).fetchall()
    assert len(docs) == 2 * (1 + 1 + 1 + 2)
    for r in repos.values():
        assert r["document_count"] == 5

    by_title = {d["title"]: d for d in docs}
    # A run no longer impersonates a code repo. It used to label its spec a "file"
    # purely to opt into co-occurrence — the single behaviour `level == 'file'` gated —
    # so the structural role and the extraction switch are now stated separately.
    assert by_title["run1 overview"]["role"] == "root"
    assert by_title["run1 overview"]["source_path"] is None  # synthetic rollup, no raw file
    # spec/dip are leaves at the run root, pointing at the STAGED raw artifact
    # (map -> territory).
    assert by_title["run1 spec"]["role"] == "leaf"
    assert by_title["run1 spec"]["parent_path"] == "."
    assert by_title["run1 spec"]["source_path"] == str(runs_dir / "run1" / "spec.md")
    assert by_title["run1 dip"]["source_path"] == str(runs_dir / "run1" / "workflow.dip")
    # Trace nodes are the one part of a run that is NOT a filesystem — one
    # activity.jsonl distilled into many docs, ordered by time. They group under
    # `trace`; their ORDER lives on the run->run chain_next edges, not in the tree.
    assert by_title["run1/Stage"]["role"] == "leaf"
    assert by_title["run1/Stage"]["parent_path"] == "trace"
    # Only leaves emit co-occurrence, and the root explicitly does not.
    assert by_title["run1 overview"]["emits_cooccurrence"] == 0
    assert {by_title[t]["emits_cooccurrence"] for t in ("run1 spec", "run1 dip", "run1/Stage")} == {1}

    # Every doc gets a chunk mirroring its content, and the run's classified domain.
    for d in docs:
        chunk = conn.execute("SELECT text, offset, length FROM chunks WHERE document_id = ?", (d["id"],)).fetchone()
        assert chunk is not None and chunk["offset"] == 0
        assert chunk["length"] == len(chunk["text"])
        dd = conn.execute(
            "SELECT is_primary FROM document_domains WHERE document_id = ? AND domain_path = ?",
            (d["id"], domain_path),
        ).fetchone()
        assert dd is not None and dd["is_primary"] == 1

    dom = conn.execute("SELECT document_count FROM domains WHERE path = ?", (domain_path,)).fetchone()
    assert dom["document_count"] == len(docs)

    # Trajectory: consecutive runs linked at the collection layer, in rung order.
    edges = conn.execute(
        "SELECT a.name AS src, b.name AS dst, e.type FROM collection_edges e "
        "JOIN collections a ON a.id = e.source JOIN collections b ON b.id = e.target"
    ).fetchall()
    assert [(e["src"], e["dst"], e["type"]) for e in edges] == [("run1", "run2", "chain_next")]

    # Phase 2 over the new code_intent docs, same handoff as ingest_repo.
    extract = conn.execute("SELECT config FROM jobs WHERE type = 'extract_batch'").fetchone()
    cfg = json.loads(extract["config"])
    assert cfg == {"spec_id": spec_id, "scope": "code_intent"}

    result = json.loads(conn.execute("SELECT result FROM jobs WHERE type = 'ingest_tracker_runs'").fetchone()["result"])
    assert result["runs"] == 2
    assert result["chain"] == ["run1", "run2"]
    assert result["chain_edges"] == 1

    conn.close()


async def test_explicit_chain_overrides_rung_order(tmp_path, monkeypatch):
    """config.chain wins over the ground-truth rung order — in production the chain
    is inferred upstream, so the job must accept it verbatim."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    out_dir, runs_dir = _make_fixture_bundle(tmp_path)
    spec_id = str(uuid.uuid4())

    # run2 is rung R0 (would sort last); an explicit chain reverses it.
    job = _seed_job(db_path, out_dir, runs_dir, spec_id, chain=["run2", "run1"])
    _stub_classify(monkeypatch, "development/agent-orchestration")

    from src.jobs.ingest_tracker_runs import run_ingest_tracker_runs
    await run_ingest_tracker_runs(job, db_path)

    conn = get_connection(db_path)
    edges = conn.execute(
        "SELECT a.name AS src, b.name AS dst FROM collection_edges e "
        "JOIN collections a ON a.id = e.source JOIN collections b ON b.id = e.target"
    ).fetchall()
    assert [(e["src"], e["dst"]) for e in edges] == [("run2", "run1")]
    conn.close()


async def test_raw_mode_summarizes_via_tracksum(tmp_path, monkeypatch):
    """No index.json -> the job summarizes raw runs in-process with orrery-tracksum,
    the same way ingest_repo summarizes a checkout with orrery-codesum."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    raw_root = tmp_path / "corpus"
    raw_root.mkdir()
    spec_id = str(uuid.uuid4())

    job = {
        "id": str(uuid.uuid4()), "type": "ingest_tracker_runs", "target": "tracker-runs",
        "config": json.dumps({"raw_root": str(raw_root), "spec_id": spec_id, "chain": None}),
    }
    conn = get_connection(db_path)
    conn.execute("INSERT INTO specs (id, domain_path, version, spec_content) VALUES (?, NULL, 1, 's')", (spec_id,))
    conn.execute("INSERT INTO jobs (id, type, target, status, config) VALUES (?, ?, ?, 'running', ?)",
                 (job["id"], job["type"], job["target"], job["config"]))
    conn.commit()
    conn.close()

    import src.jobs.ingest_tracker_runs as mod

    # Stub tracksum's batch summarizer — the package has its own tests; here we only
    # care that the job takes the raw path and persists what it returns.
    def fake_summarize_runs(root, summarize_fn, reader, on_progress=None):
        assert root == str(raw_root)
        return [{
            "run_label": "runA", "rung": "R0", "source_path": str(raw_root / "runA"),
            "rollup": "runA overview", "spec": {"text": "spec body", "artifacts": ["SPEC.md"]},
            "dip": {"recognized": "PATTERNS: gate-then-retry-loop"},
            "nodes": [{"node": "Build", "summary": "wrote src/store.js"}],
        }]

    monkeypatch.setattr(mod, "summarize_runs", fake_summarize_runs)
    monkeypatch.setattr(mod, "make_summarize_fn", lambda relay, model: (lambda *a, **k: ""))
    monkeypatch.setattr(mod, "_tracksum_reader", lambda settings: object())
    _stub_classify(monkeypatch, "development/agent-orchestration")

    await mod.run_ingest_tracker_runs(job, db_path)

    conn = get_connection(db_path)
    titles = {r["title"] for r in conn.execute(
        "SELECT title FROM documents WHERE content_type = 'code_intent'").fetchall()}
    assert titles == {"runA overview", "runA spec", "runA dip", "runA/Build"}
    # The raw run dir has no workflow.dip on disk here, and the staged fallback does not
    # exist either — so no dangling source_path is advertised.
    assert conn.execute(
        "SELECT source_path FROM documents WHERE title = 'runA dip'").fetchone()["source_path"] is None
    conn.close()


async def test_raw_mode_without_distill_fails_with_actionable_message(tmp_path, monkeypatch):
    """orrery-tracksum takes an injected reader rather than vendoring tracker's log
    parser, so raw mode needs distill importable — and must say exactly that."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    raw_root = tmp_path / "corpus"
    raw_root.mkdir()

    import src.jobs.ingest_tracker_runs as mod
    monkeypatch.setattr(mod, "distill_reader", lambda d: object())
    monkeypatch.setitem(__import__("sys").modules, "distill", None)  # force ImportError

    class S:
        tracker_distill_path = ""

    with pytest.raises(RuntimeError, match="TRACKER_DISTILL_PATH"):
        mod._tracksum_reader(S())


@pytest.mark.parametrize("label", [
    "../escape", "..", ".", "a/b", "/abs/path", "", None, 42, "has space", "semi;colon",
])
def test_unsafe_run_labels_are_rejected(label):
    """run_label is DATA from a summary JSON, but it becomes a path segment under
    runs_dir and the UNIQUE repos.path key — same rule prepare.sh applies to repo
    names."""
    from src.jobs.ingest_tracker_runs import _safe_label
    assert _safe_label(label) is False


@pytest.mark.parametrize("label", ["run1", "run-4", "run_4", "R0.brief", "abc123"])
def test_safe_run_labels_accepted(label):
    from src.jobs.ingest_tracker_runs import _safe_label
    assert _safe_label(label) is True


async def test_run_with_unsafe_label_is_skipped(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    out_dir, runs_dir = _make_fixture_bundle(tmp_path)
    # A traversing label in both the index and its own bundle file.
    _write_run(out_dir, runs_dir, "evil", "R5")
    (out_dir / "evil.json").write_text(json.dumps({
        "run_label": "../../evil", "rung": "R5", "rollup": "x",
        "spec": {"text": "spec body"}, "dip": {}, "nodes": [],
    }))
    index = json.loads((out_dir / "index.json").read_text())
    index.append({"run_label": "evil"})
    (out_dir / "index.json").write_text(json.dumps(index))

    spec_id = str(uuid.uuid4())
    job = _seed_job(db_path, out_dir, runs_dir, spec_id)
    _stub_classify(monkeypatch, "development/agent-orchestration")

    from src.jobs.ingest_tracker_runs import run_ingest_tracker_runs
    await run_ingest_tracker_runs(job, db_path)

    conn = get_connection(db_path)
    names = {r["name"] for r in conn.execute("SELECT name FROM collections").fetchall()}
    assert names == {"run1", "run2"}  # the traversing label never became a repo
    conn.close()


def test_spec_fallback_uses_the_allowlist_not_bundle_supplied_paths(tmp_path):
    """With no embedded `text`, the fallback re-reads via tracksum's gather_spec, which
    resolves only its own SPEC_ARTIFACTS names — so a bundle cannot name a path to read."""
    from src.jobs.ingest_tracker_runs import _spec_text

    checkout = tmp_path / "flagship"
    checkout.mkdir()
    (checkout / "SPEC.md").write_text("real spec")
    secret = tmp_path / "secret.md"
    secret.write_text("SHOULD NOT BE READ")

    run = {
        "run_label": "run1",
        "source_path": str(checkout / ".tracker" / "runs" / "run-1"),
        "spec": {"artifacts": ["../secret.md", "/etc/hostname"]},  # ignored
    }
    text = _spec_text(run)
    assert text == "real spec"
    assert "SHOULD NOT BE READ" not in text


def test_spec_text_prefers_the_embedded_bundle_text():
    assert _spec_text_of({"spec": {"text": "  embedded  "}}) == "embedded"
    assert _spec_text_of({"spec": {}}) == ""  # no source_path -> nothing to re-read


def _spec_text_of(run):
    from src.jobs.ingest_tracker_runs import _spec_text
    return _spec_text(run)


async def test_an_existing_run_label_aborts_before_any_row_is_written(tmp_path, monkeypatch):
    """The worker owns the uniqueness guarantee, because only it knows every label.

    `collections.path` is UNIQUE, so a label that already exists raises mid-loop — after
    earlier runs are inserted — leaving a partial trajectory whose chain_next edges are
    incomplete without saying so. The route's 409 is an early convenience (and in raw
    mode it cannot know the labels at all); this preflight is the actual guarantee.
    """
    import json
    import uuid

    import pytest

    from src.db import get_connection, init_db

    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    out = tmp_path / "out"
    out.mkdir()
    (out / "index.json").write_text(json.dumps([{"run_label": "runA"}, {"run_label": "runB"}]))
    for label in ("runA", "runB"):
        (out / f"{label}.json").write_text(json.dumps(
            {"run_label": label, "rollup": f"{label} overview",
             "spec": {"text": "do a thing"}, "nodes": []}))

    conn = get_connection(db_path)
    conn.execute("INSERT INTO specs (id, domain_path, version, spec_content) "
                 "VALUES ('spec1', NULL, 1, 'x')")
    # runB already ingested — runA is new, so a naive loop would insert it then die.
    conn.execute("INSERT INTO collections (id, name, path, root_path, kind) "
                 "VALUES ('existing', 'runB', 'runB', '/x', 'tracker_run')")
    conn.commit()
    conn.close()

    import src.jobs.ingest_tracker_runs as mod

    async def fake_classify(**kw):
        return {"primary_domain": "software/agents/codegen", "secondary_domains": [],
                "confidence": 0.9}

    monkeypatch.setattr(mod, "classify_document", fake_classify)
    monkeypatch.setattr(mod, "Relay", type("R", (), {
        "from_settings": classmethod(lambda cls, s, **k: cls())}))

    job = {"id": str(uuid.uuid4()), "config": json.dumps(
        {"out_dir": str(out), "spec_id": "spec1", "runs_dir": str(tmp_path / "runs")})}

    with pytest.raises(RuntimeError, match="already exist"):
        await mod.run_ingest_tracker_runs(job, db_path)

    conn = get_connection(db_path)
    names = {r[0] for r in conn.execute("SELECT name FROM collections")}
    docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    conn.close()
    assert names == {"runB"}, f"a row was written before the abort: {names}"
    assert docs == 0, "documents were written despite the refusal"
