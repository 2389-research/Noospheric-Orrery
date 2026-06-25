import json
import pytest
from unittest.mock import AsyncMock, patch
from src.db import init_db, get_connection


def _seed_docs_and_chunks(db_path, n=3):
    conn = get_connection(db_path)
    for i in range(n):
        conn.execute("INSERT INTO documents (id, title, content, status) VALUES (?, ?, ?, 'classified')",
                     (f"d{i}", f"Doc {i}", f"Content about topic {i}"))
        conn.execute("INSERT INTO chunks (id, document_id, chunk_index, text) VALUES (?, ?, 0, ?)",
                     (f"c{i}", f"d{i}", f"Content about topic {i}: Alice met Acme Corp."))
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_simmer_general_creates_spec(tmp_path):
    db_path = str(tmp_path / "test.db")
    specs_dir = str(tmp_path / "specs")
    init_db(db_path)
    _seed_docs_and_chunks(db_path)

    # Phase 1 (judged golden loop) and Phase 2 (rules-loop) make LLM calls — mock them.
    golden_md = '# Golden Set\n```json\n[{"name": "alice", "type": "person"}]\n```'
    with patch("src.jobs.simmer_general._build_golden_set_judged", new_callable=AsyncMock,
               return_value=golden_md), \
         patch("src.jobs.simmer_general._refine_spec_rules", new_callable=AsyncMock,
               return_value=("# Entity Extraction Specification\n## Rules\n### INCLUDE Rules\n...", 7.5)), \
         patch("src.jobs.simmer_general.get_settings") as mock_settings:
        mock_settings.return_value.simmer_iterations = 2
        mock_settings.return_value.specs_dir = specs_dir
        mock_settings.return_value.anthropic_backend = "ollama"
        mock_settings.return_value.ollama_url = "http://localhost:11434"

        from src.jobs.simmer_general import run_simmer_general
        await run_simmer_general({"id": "j1", "type": "simmer_general", "target": "general", "config": None}, db_path)

    conn = get_connection(db_path)
    spec = conn.execute("SELECT spec_content, score FROM specs WHERE domain_path IS NULL").fetchone()
    assert spec is not None
    assert spec[1] == 7.5
    # Should also queue an extract_batch job
    batch_job = conn.execute("SELECT * FROM jobs WHERE type = 'extract_batch'").fetchone()
    assert batch_job is not None
    conn.close()


@pytest.mark.asyncio
async def test_simmer_general_raises_when_no_chunks(tmp_path):
    db_path = str(tmp_path / "test.db")
    specs_dir = str(tmp_path / "specs")
    init_db(db_path)  # documents/chunks intentionally empty

    with patch("src.jobs.simmer_general.get_settings") as mock_settings:
        mock_settings.return_value.simmer_iterations = 1
        mock_settings.return_value.specs_dir = specs_dir

        from src.jobs.simmer_general import run_simmer_general
        with pytest.raises(ValueError, match="No chunks available"):
            await run_simmer_general({"id": "j1", "type": "simmer_general", "target": "general", "config": None}, db_path)


@pytest.mark.asyncio
async def test_golden_phase_is_judged_not_bare_map(tmp_path):
    """Regression guard for #27: the golden phase MUST run a judge — recording scored iterations
    with ASI — not silently degrade to a bare map with no evaluation."""
    import types
    from simmer_sdk import JudgeOutput

    db_path = str(tmp_path / "g.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('jg','simmer_domain','t','running')")
    conn.commit(); conn.close()

    sample_chunks = [("c0", "Alice met Acme Corp.", "Doc0"), ("c1", "Bob joined Beta Inc.", "Doc1")]
    empty_golden = "# Golden Set\n\n## Entity Type Taxonomy\n- person — people\n\n## Reference Entities\n```json\n[]\n```"
    judgments = [JudgeOutput(scores={"coverage": 7, "precision": 8}, asi="add the missing org names", reasoning={"coverage": "r"})
                 for _ in range(3)]

    with patch("src.jobs.simmer_general._build_golden_set_mapreduce", new_callable=AsyncMock, return_value=empty_golden), \
         patch("src.jobs.simmer_general._generate_golden", new_callable=AsyncMock, return_value=empty_golden), \
         patch("src.jobs.simmer_core.relay_judge", new=AsyncMock(side_effect=judgments)):
        from src.jobs.simmer_general import _build_golden_set_judged
        await _build_golden_set_judged(sample_chunks, types.SimpleNamespace(classification_model="m", extraction_model="e"),
                                       "jg", db_path, iterations=2)

    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT scores, composite, asi FROM simmer_iterations WHERE job_id='jg' AND phase='golden_set' ORDER BY iteration"
    ).fetchall()
    conn.close()
    assert len(rows) == 3                       # a judged loop ran, not a one-shot map
    for scores, composite, asi in rows:
        assert json.loads(scores) != {}         # the judge produced scores
        assert composite is not None
        assert asi                              # the judge produced an ASI
