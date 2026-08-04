import sqlite3
import os
import threading
from pathlib import Path

# Paths already migrated by init_db in this process. The schema + migrations
# only need to run once per DB file per process — repeating them takes a write
# lock and contends with concurrent requests / the worker.
_initialized: set[str] = set()
_init_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT,
    source_path TEXT,
    content TEXT,
    content_hash TEXT,
    metadata TEXT,
    content_type TEXT DEFAULT 'text',
    thumbnail_path TEXT,
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
    text TEXT,
    embedding BLOB,
    image_embedding BLOB
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

CREATE TABLE IF NOT EXISTS repos (
    id TEXT PRIMARY KEY,
    name TEXT,
    path TEXT UNIQUE,
    root_path TEXT,
    parent_path TEXT,
    document_count INTEGER DEFAULT 0,
    remote_url TEXT,
    commit_sha TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS document_repos (
    document_id TEXT REFERENCES documents(id),
    repo_id TEXT REFERENCES repos(id),
    level TEXT,
    parent_path TEXT,
    PRIMARY KEY (document_id, repo_id)
);
CREATE INDEX IF NOT EXISTS idx_document_repos_repo ON document_repos(repo_id);
CREATE TABLE IF NOT EXISTS repo_edges (
    from_repo TEXT REFERENCES repos(id),
    to_repo TEXT REFERENCES repos(id),
    type TEXT,
    weight REAL DEFAULT 1.0,
    PRIMARY KEY (from_repo, to_repo, type)
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    canonical_name TEXT,
    type TEXT,
    embedding BLOB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entity_sources (
    entity_id TEXT REFERENCES entities(id),
    document_id TEXT REFERENCES documents(id),
    chunk_id TEXT REFERENCES chunks(id),
    extraction_pass TEXT,
    spec_version INTEGER,
    job_id TEXT REFERENCES jobs(id)
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

CREATE TABLE IF NOT EXISTS graph_issues (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,                 -- invalidate | merge | retype | rename
    target_entity_id TEXT NOT NULL REFERENCES entities(id),
    target_entity_name TEXT NOT NULL,
    target_b_entity_id TEXT REFERENCES entities(id),  -- merge: the other node
    target_b_name TEXT,
    proposed_type TEXT,                   -- retype
    proposed_name TEXT,                   -- rename
    rationale TEXT,
    proposer TEXT,                        -- proposing agent id
    status TEXT NOT NULL DEFAULT 'pending', -- pending | accepted | rejected
    judge_verdict TEXT,                   -- advisory, written by the judge stage
    judge_confidence REAL,                -- advisory
    judge_rationale TEXT,                 -- advisory
    reviewer TEXT,                        -- human, written on resolve
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_graph_issues_status ON graph_issues(status);
CREATE INDEX IF NOT EXISTS idx_graph_issues_target ON graph_issues(target_entity_id);

CREATE TABLE IF NOT EXISTS simmer_iterations (
    id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES jobs(id),
    phase TEXT,
    iteration INTEGER,
    scores TEXT,
    composite REAL,
    key_change TEXT,
    asi TEXT,
    judge_mode TEXT,
    regressed BOOLEAN,
    candidate_preview TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_simmer_iterations_job ON simmer_iterations(job_id);

CREATE TABLE IF NOT EXISTS simmer_criterion_details (
    id TEXT PRIMARY KEY,
    iteration_id TEXT REFERENCES simmer_iterations(id),
    criterion TEXT,
    score INTEGER,
    seed_score INTEGER,
    evidence TEXT,
    improve TEXT
);


CREATE TABLE IF NOT EXISTS domain_layout (
    domain_path TEXT PRIMARY KEY,
    x REAL,
    y REAL,
    embedding BLOB,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS layout_model (
    id TEXT PRIMARY KEY DEFAULT 'umap',
    model_blob BLOB,
    domain_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS specs (
    id TEXT PRIMARY KEY,
    domain_path TEXT,
    version INTEGER,
    spec_content TEXT,
    golden_set TEXT,
    score REAL,
    media_type TEXT DEFAULT 'text',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Materialized read-model of the /graph payload. One logical row (id='current').
-- The graph only changes when a job writes to it, so we compute the payload once
-- and serve it cached. Writers flip `dirty=1`; the orchestrator rebuilds in the
-- background. See orchestrator/src/pipeline/graph_snapshot.py.
CREATE TABLE IF NOT EXISTS graph_snapshot (
    id TEXT PRIMARY KEY DEFAULT 'current',
    payload TEXT,
    built_at TIMESTAMP,
    entity_count INTEGER DEFAULT 0,
    edge_count INTEGER DEFAULT 0,
    dirty INTEGER DEFAULT 1
);
"""

def init_db(db_path: str) -> None:
    # Fast path: skip migrations if we've already initialized this DB in this process.
    if db_path in _initialized:
        return
    with _init_lock:
        if db_path in _initialized:
            return
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.executescript(SCHEMA)
            # Migrate: add columns for image support if missing
            cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
            if "content_type" not in cols:
                conn.execute("ALTER TABLE documents ADD COLUMN content_type TEXT DEFAULT 'text'")
            if "thumbnail_path" not in cols:
                conn.execute("ALTER TABLE documents ADD COLUMN thumbnail_path TEXT")
            # Migrate specs table
            spec_cols = {r[1] for r in conn.execute("PRAGMA table_info(specs)").fetchall()}
            if "media_type" not in spec_cols:
                conn.execute("ALTER TABLE specs ADD COLUMN media_type TEXT DEFAULT 'text'")
            # Migrate chunks table — SigLIP image embedding column
            chunk_cols = {r[1] for r in conn.execute("PRAGMA table_info(chunks)").fetchall()}
            if "image_embedding" not in chunk_cols:
                conn.execute("ALTER TABLE chunks ADD COLUMN image_embedding BLOB")
            if "section" not in chunk_cols:
                conn.execute("ALTER TABLE chunks ADD COLUMN section TEXT")
            # Backfill: tag legacy image rows by file extension
            conn.execute("""
                UPDATE documents SET content_type = 'image'
                WHERE (content_type IS NULL OR content_type = 'text')
                AND (source_path LIKE '%.jpg' OR source_path LIKE '%.jpeg'
                     OR source_path LIKE '%.png' OR source_path LIKE '%.webp'
                     OR source_path LIKE '%.gif')
            """)
            # Migrate: graph self-healing soft-delete + generalized correction log
            ent_cols = {r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()}
            if "invalid_at" not in ent_cols:
                conn.execute("ALTER TABLE entities ADD COLUMN invalid_at TIMESTAMP")
            if "invalid_reason" not in ent_cols:
                conn.execute("ALTER TABLE entities ADD COLUMN invalid_reason TEXT")
            if "updated_at" not in ent_cols:
                conn.execute("ALTER TABLE entities ADD COLUMN updated_at TIMESTAMP")
            rel_cols = {r[1] for r in conn.execute("PRAGMA table_info(relationships)").fetchall()}
            if "invalid_at" not in rel_cols:
                conn.execute("ALTER TABLE relationships ADD COLUMN invalid_at TIMESTAMP")
            if "invalid_reason" not in rel_cols:
                conn.execute("ALTER TABLE relationships ADD COLUMN invalid_reason TEXT")
            log_cols = {r[1] for r in conn.execute("PRAGMA table_info(normalization_log)").fetchall()}
            for col, decl in [
                ("action", "TEXT"), ("before_value", "TEXT"), ("after_value", "TEXT"),
                ("actor", "TEXT"), ("reason", "TEXT"), ("model_verdict", "TEXT"),
                ("model_confidence", "REAL"), ("reviewer", "TEXT"),
            ]:
                if col not in log_cols:
                    conn.execute(f"ALTER TABLE normalization_log ADD COLUMN {col} {decl}")
            # Backfill: existing merge-log rows predate `action`
            conn.execute("UPDATE normalization_log SET action = 'merge' WHERE action IS NULL")
            # entity_sources has no PK; without these indexes the graph build's
            # per-entity source_count + the trade-route/repo self-joins scan the
            # whole table (30s+ on a large graph). Also speeds entities.list.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_sources_entity ON entity_sources(entity_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_sources_document ON entity_sources(document_id)")
            # Seed the single snapshot row (dirty, empty) so writers can flip the
            # dirty bit with a plain UPDATE even before the first build.
            conn.execute(
                "INSERT OR IGNORE INTO graph_snapshot (id, dirty) VALUES ('current', 1)"
            )
            conn.commit()
        finally:
            conn.close()
        _initialized.add(db_path)


def mark_graph_dirty(conn) -> None:
    """Flag the cached /graph snapshot for rebuild.

    Called after any write that changes the graph (ingest, extract, normalize,
    corrections). One idempotent DB write; the orchestrator's background task
    debounces bursts into a single rebuild. The caller owns the commit.
    """
    conn.execute(
        "INSERT INTO graph_snapshot (id, dirty) VALUES ('current', 1) "
        "ON CONFLICT(id) DO UPDATE SET dirty = 1"
    )


def reset_initialized(db_path: str | None = None) -> None:
    """Test helper: clear the init guard for a path (or all paths)."""
    with _init_lock:
        if db_path is None:
            _initialized.clear()
        else:
            _initialized.discard(db_path)


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn
