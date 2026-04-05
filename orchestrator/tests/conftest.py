import os
import pytest

# Set env vars before any imports
os.environ.setdefault("AWS_ACCESS_KEY", "test-key")
os.environ.setdefault("AWS_SECRET_KEY", "test-secret")
os.environ.setdefault("AWS_REGION", "us-east-1")

from src.db import init_db
from src.repositories.sqlite_store import SQLiteDataStore
from src.repositories.factory import set_test_store


@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


@pytest.fixture
def test_store(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    store = SQLiteDataStore(db_path)
    set_test_store(store)
    yield store
    set_test_store(None)
    store.close()


@pytest.fixture
def test_client(test_store):
    from src.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    yield client
