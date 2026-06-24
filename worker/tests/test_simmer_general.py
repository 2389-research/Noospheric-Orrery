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
