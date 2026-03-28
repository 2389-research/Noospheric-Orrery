import sqlite3
import os
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT,
    source_path TEXT,
    content TEXT,
    content_hash TEXT,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT REFERENCES documents(id),
    chunk_index INTEGER,
    offset INTEGER,
    length INTEGER,
    text TEXT
);

CREATE TABLE IF NOT EXISTS domains (
    id TEXT PRIMARY KEY,
    path TEXT UNIQUE,
    parent_path TEXT,
    document_count INTEGER DEFAULT 0,
    spec_version INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS domain_merge_map (
    from_label TEXT PRIMARY KEY,
    to_path TEXT REFERENCES domains(path)
);

CREATE TABLE IF NOT EXISTS document_domains (
    document_id TEXT REFERENCES documents(id),
    domain_path TEXT REFERENCES domains(path),
    is_primary BOOLEAN,
    confidence REAL,
    PRIMARY KEY (document_id, domain_path)
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    canonical_name TEXT,
    type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entity_sources (
    entity_id TEXT REFERENCES entities(id),
    document_id TEXT REFERENCES documents(id),
    chunk_id TEXT REFERENCES chunks(id),
    extraction_pass TEXT,
    spec_version INTEGER
);

CREATE TABLE IF NOT EXISTS merge_map (
    from_name TEXT PRIMARY KEY,
    to_entity_id TEXT REFERENCES entities(id)
);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    from_entity TEXT REFERENCES entities(id),
    to_entity TEXT REFERENCES entities(id),
    type TEXT,
    weight REAL,
    source_chunk TEXT REFERENCES chunks(id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT,
    target TEXT,
    status TEXT DEFAULT 'queued',
    config TEXT,
    result TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entity_embeddings (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id),
    embedding BLOB
);

CREATE TABLE IF NOT EXISTS normalization_log (
    id TEXT PRIMARY KEY,
    from_entity_id TEXT,
    from_name TEXT,
    to_entity_id TEXT,
    to_name TEXT,
    method TEXT,
    similarity REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS normalization_review_queue (
    id TEXT PRIMARY KEY,
    entity_a_id TEXT,
    entity_a_name TEXT,
    entity_b_id TEXT,
    entity_b_name TEXT,
    similarity REAL,
    status TEXT DEFAULT 'pending',
    resolution TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS specs (
    id TEXT PRIMARY KEY,
    domain_path TEXT,
    version INTEGER,
    spec_content TEXT,
    golden_set TEXT,
    score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    conn.close()

def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
