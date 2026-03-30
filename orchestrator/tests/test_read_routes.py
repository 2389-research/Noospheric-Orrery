"""Tests for read-only routes: stats, documents, domains, entities, jobs, simmer."""

import uuid


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------

def test_stats_empty_db(test_client, test_store):
    response = test_client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["document_count"] == 0
    assert data["entity_count"] == 0
    assert data["domain_count"] == 0
    assert data["active_jobs"] == 0


def test_stats_returns_counts(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc 1', 'extracted')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'test', 'Thing')")
    conn.execute("INSERT INTO domains (id, path, document_count) VALUES ('dm1', 'techniques', 1)")
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'queued')")
    conn.commit()

    response = test_client.get("/stats")
    data = response.json()
    assert data["document_count"] == 1
    assert data["entity_count"] == 1
    assert data["domain_count"] == 1
    assert data["active_jobs"] == 1


# ---------------------------------------------------------------------------
# /documents
# ---------------------------------------------------------------------------

def test_list_documents_empty(test_client):
    response = test_client.get("/documents")
    assert response.status_code == 200
    assert response.json() == []


def test_list_documents_returns_rows(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'My Doc', 'classified')")
    conn.commit()

    response = test_client.get("/documents")
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "My Doc"
    assert data[0]["status"] == "classified"


def test_get_document_not_found(test_client):
    response = test_client.get("/documents/nonexistent")
    assert response.status_code == 404


def test_get_document_detail(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO documents (id, title, content, status) VALUES ('d1', 'Doc', 'Hello world', 'extracted')")
    conn.execute("INSERT INTO domains (id, path, document_count) VALUES ('dm1', 'test/domain', 1)")
    conn.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES ('d1', 'test/domain', 1, 0.9)")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'Entity One', 'Thing')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES ('e1', 'd1')")
    conn.commit()

    response = test_client.get("/documents/d1")
    data = response.json()
    assert data["id"] == "d1"
    assert data["title"] == "Doc"
    assert len(data["domains"]) == 1
    assert data["domains"][0]["path"] == "test/domain"
    assert len(data["entities"]) == 1


# ---------------------------------------------------------------------------
# /domains
# ---------------------------------------------------------------------------

def test_list_domains_empty(test_client):
    response = test_client.get("/domains")
    assert response.status_code == 200
    assert response.json() == []


def test_list_domains_returns_rows(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO domains (id, path, document_count) VALUES ('dm1', 'art/painting', 5)")
    conn.commit()

    response = test_client.get("/domains")
    data = response.json()
    assert len(data) == 1
    assert data[0]["path"] == "art/painting"
    assert data[0]["document_count"] == 5


# ---------------------------------------------------------------------------
# /entities
# ---------------------------------------------------------------------------

def test_list_entities_empty(test_client):
    response = test_client.get("/entities")
    assert response.status_code == 200
    assert response.json() == []


def test_list_entities_with_type_filter(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'Alice', 'Person')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e2', 'Widget', 'Product')")
    conn.commit()

    response = test_client.get("/entities?type=Person")
    data = response.json()
    assert len(data) == 1
    assert data[0]["canonical_name"] == "Alice"


def test_get_entity_not_found(test_client):
    response = test_client.get("/entities/nonexistent")
    assert response.status_code == 404


def test_get_entity_detail(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'Alice', 'Person')")
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc', 'extracted')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id, chunk_id) VALUES ('e1', 'd1', 'c1')")
    conn.commit()

    response = test_client.get("/entities/e1")
    data = response.json()
    assert data["canonical_name"] == "Alice"
    assert data["type"] == "Person"
    assert len(data["sources"]) == 1


# ---------------------------------------------------------------------------
# /jobs
# ---------------------------------------------------------------------------

def test_list_jobs_empty(test_client):
    response = test_client.get("/jobs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_jobs_with_status_filter(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'queued')")
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j2', 'extract_batch', 'test', 'completed')")
    conn.commit()

    response = test_client.get("/jobs?status=queued")
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "j1"


# ---------------------------------------------------------------------------
# /simmer
# ---------------------------------------------------------------------------

def test_trigger_general_simmer(test_client):
    response = test_client.post("/simmer/general")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert "job_id" in data


def test_trigger_general_simmer_conflict(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_general', 'general', 'running')")
    conn.commit()

    response = test_client.post("/simmer/general")
    assert response.status_code == 409


def test_trigger_domain_simmer(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO domains (id, path) VALUES ('dm1', 'test/domain')")
    conn.commit()

    response = test_client.post("/simmer/test/domain")
    assert response.status_code == 200


def test_trigger_domain_simmer_not_found(test_client):
    response = test_client.post("/simmer/nonexistent/domain")
    assert response.status_code == 404


def test_trigger_domain_simmer_conflict(test_client, test_store):
    conn = test_store.conn
    conn.execute("INSERT INTO domains (id, path) VALUES ('dm1', 'test/domain')")
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES ('j1', 'simmer_domain', 'test/domain', 'queued')")
    conn.commit()

    response = test_client.post("/simmer/test/domain")
    assert response.status_code == 409
