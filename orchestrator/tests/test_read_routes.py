# ABOUTME: Integration tests for read-only routes (stats, documents, domains, entities, jobs, simmer).
# ABOUTME: Uses patched Settings to isolate each test with a temporary SQLite database.

import uuid
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.db import init_db, get_connection
from src.config import Settings


def make_settings(tmp_path):
    return Settings(
        db_path=str(tmp_path / "test.db"),
        documents_dir=str(tmp_path / "documents"),
    )


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------

def test_stats_empty_db(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.stats.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["document_count"] == 0
    assert data["entity_count"] == 0
    assert data["domain_count"] == 0
    assert data["active_jobs"] == 0


def test_stats_returns_counts(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)
    conn = get_connection(settings.db_path)
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc 1', 'extracted')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'test', 'Thing')")
    conn.execute("INSERT INTO domains (id, path, document_count) VALUES ('dm1', 'techniques', 1)")
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'queued')")
    conn.commit()
    conn.close()

    with patch("src.routes.stats.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["document_count"] == 1
    assert data["entity_count"] == 1
    assert data["domain_count"] == 1
    assert data["active_jobs"] == 1


# ---------------------------------------------------------------------------
# /documents
# ---------------------------------------------------------------------------

def test_list_documents_empty(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.documents.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/documents")

    assert response.status_code == 200
    assert response.json() == []


def test_list_documents_returns_rows(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)
    conn = get_connection(settings.db_path)
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc One', 'extracted')")
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d2', 'Doc Two', 'pending')")
    conn.commit()
    conn.close()

    with patch("src.routes.documents.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/documents")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    titles = {d["title"] for d in data}
    assert "Doc One" in titles
    assert "Doc Two" in titles


def test_get_document_not_found(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.documents.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/documents/nonexistent")

    assert response.status_code == 404


def test_get_document_detail(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)
    conn = get_connection(settings.db_path)
    conn.execute("INSERT INTO documents (id, title, status, content) VALUES ('d1', 'My Doc', 'extracted', 'hello')")
    conn.execute("INSERT INTO domains (id, path) VALUES ('dm1', 'techniques')")
    conn.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES ('d1', 'techniques', 1, 0.9)")
    conn.commit()
    conn.close()

    with patch("src.routes.documents.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/documents/d1")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "d1"
    assert data["title"] == "My Doc"
    assert len(data["domains"]) == 1
    assert data["domains"][0]["path"] == "techniques"
    assert data["domains"][0]["is_primary"] is True


# ---------------------------------------------------------------------------
# /domains
# ---------------------------------------------------------------------------

def test_list_domains_empty(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.domains.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/domains")

    assert response.status_code == 200
    assert response.json() == []


def test_list_domains_returns_rows(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)
    conn = get_connection(settings.db_path)
    conn.execute("INSERT INTO domains (id, path, document_count) VALUES ('dm1', 'techniques', 3)")
    conn.execute("INSERT INTO domains (id, path, parent_path, document_count) VALUES ('dm2', 'techniques/blending', 'techniques', 1)")
    conn.commit()
    conn.close()

    with patch("src.routes.domains.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/domains")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    paths = [d["path"] for d in data]
    assert "techniques" in paths
    assert "techniques/blending" in paths


# ---------------------------------------------------------------------------
# /entities
# ---------------------------------------------------------------------------

def test_list_entities_empty(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.entities.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/entities")

    assert response.status_code == 200
    assert response.json() == []


def test_list_entities_with_type_filter(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)
    conn = get_connection(settings.db_path)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'Citadel', 'Brand')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e2', 'Abaddon Black', 'Paint')")
    conn.commit()
    conn.close()

    with patch("src.routes.entities.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/entities?type=Paint")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["canonical_name"] == "Abaddon Black"


def test_get_entity_not_found(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.entities.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/entities/nonexistent")

    assert response.status_code == 404


def test_get_entity_detail(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)
    conn = get_connection(settings.db_path)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'Citadel', 'Brand')")
    conn.execute("INSERT INTO merge_map (from_name, to_entity_id) VALUES ('Citadel Colour', 'e1')")
    conn.commit()
    conn.close()

    with patch("src.routes.entities.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/entities/e1")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "e1"
    assert data["canonical_name"] == "Citadel"
    assert "Citadel Colour" in data["merge_history"]


# ---------------------------------------------------------------------------
# /jobs
# ---------------------------------------------------------------------------

def test_list_jobs_empty(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.jobs.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/jobs")

    assert response.status_code == 200
    assert response.json() == []


def test_list_jobs_with_status_filter(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)
    conn = get_connection(settings.db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'queued')")
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j2', 'simmer_general', 'general', 'completed')")
    conn.commit()
    conn.close()

    with patch("src.routes.jobs.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.get("/jobs?status=queued")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "j1"


# ---------------------------------------------------------------------------
# /simmer/general
# ---------------------------------------------------------------------------

def test_trigger_general_simmer(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.simmer.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.post("/simmer/general")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert "job_id" in data

    conn = get_connection(settings.db_path)
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (data["job_id"],)).fetchone()
    assert job is not None
    assert job["type"] == "simmer_general"
    conn.close()


def test_trigger_general_simmer_conflict(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)
    conn = get_connection(settings.db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'queued')")
    conn.commit()
    conn.close()

    with patch("src.routes.simmer.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.post("/simmer/general")

    assert response.status_code == 409


def test_trigger_domain_simmer(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)
    conn = get_connection(settings.db_path)
    conn.execute("INSERT INTO domains (id, path) VALUES ('dm1', 'techniques/blending')")
    conn.commit()
    conn.close()

    with patch("src.routes.simmer.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.post("/simmer/techniques/blending")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert "job_id" in data


def test_trigger_domain_simmer_not_found(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)

    with patch("src.routes.simmer.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.post("/simmer/nonexistent/domain")

    assert response.status_code == 404


def test_trigger_domain_simmer_conflict(tmp_path):
    settings = make_settings(tmp_path)
    init_db(settings.db_path)
    conn = get_connection(settings.db_path)
    conn.execute("INSERT INTO domains (id, path) VALUES ('dm1', 'techniques')")
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_domain', 'techniques', 'running')")
    conn.commit()
    conn.close()

    with patch("src.routes.simmer.get_settings", return_value=settings), \
         patch("src.main.get_settings", return_value=settings):
        from src.main import app
        client = TestClient(app)
        response = client.post("/simmer/techniques")

    assert response.status_code == 409
