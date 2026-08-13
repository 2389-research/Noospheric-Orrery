import os
import sys

# macOS-only: faiss-cpu and torch each bundle their own OpenMP runtime, and loading
# both in one process aborts with the libomp duplicate-runtime guard. Docker/Linux
# (CI + the Spark) uses a single libgomp and is unaffected — the orchestrator already
# runs faiss + torch together there. Set before any test imports torch/faiss so a
# local `pytest` does not abort. Must precede the `src.db` import below, which is why
# it sits at the very top of the file rather than beside the fixture.
if sys.platform == "darwin":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import pytest
from src.db import init_db

@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path
