import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.db import init_db, get_connection

@pytest.mark.asyncio
async def test_simmer_general_creates_spec(tmp_path):
    db_path = str(tmp_path / "test.db")
    specs_dir = str(tmp_path / "specs")
    init_db(db_path)
    conn = get_connection(db_path)
    for i in range(3):
        conn.execute("INSERT INTO documents (id, title, content, status) VALUES (?, ?, ?, 'classified')",
            (f"d{i}", f"Doc {i}", f"Content about topic {i}"))
    conn.commit()
    conn.close()

    mock_result = MagicMock()
    mock_result.best_candidate = "Extract Person, Thing, Topic from text..."
    mock_result.composite = 7.5
    mock_result.best_scores = {"coverage": 8, "precision": 7}

    with patch("src.jobs.simmer_general.refine", new_callable=AsyncMock, return_value=mock_result), \
         patch("src.jobs.simmer_general.get_settings") as mock_settings:
        mock_settings.return_value.simmer_iterations = 2
        mock_settings.return_value.specs_dir = specs_dir

        from src.jobs.simmer_general import run_simmer_general
        await run_simmer_general({"id": "j1", "type": "simmer_general", "target": "general", "config": None}, db_path)

    conn = get_connection(db_path)
    spec = conn.execute("SELECT * FROM specs WHERE domain_path IS NULL").fetchone()
    assert spec is not None
    # Should also queue an extract_batch job
    batch_job = conn.execute("SELECT * FROM jobs WHERE type = 'extract_batch'").fetchone()
    assert batch_job is not None
    conn.close()

@pytest.mark.asyncio
async def test_simmer_general_raises_when_no_docs(tmp_path):
    db_path = str(tmp_path / "test.db")
    specs_dir = str(tmp_path / "specs")
    init_db(db_path)

    mock_result = MagicMock()
    mock_result.best_candidate = "spec content"
    mock_result.composite = 7.0

    with patch("src.jobs.simmer_general.refine", new_callable=AsyncMock, return_value=mock_result), \
         patch("src.jobs.simmer_general.get_settings") as mock_settings:
        mock_settings.return_value.simmer_iterations = 1
        mock_settings.return_value.specs_dir = specs_dir

        from src.jobs.simmer_general import run_simmer_general
        with pytest.raises(ValueError, match="No documents available"):
            await run_simmer_general({"id": "j1", "type": "simmer_general", "target": "general", "config": None}, db_path)
