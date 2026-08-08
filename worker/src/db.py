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
    status TEXT DEFAULT 'pending',
    content_type TEXT DEFAULT 'text',
    thumbnail_path TEXT
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


CREATE TABLE IF NOT EXISTS specs (
    id TEXT PRIMARY KEY,
    domain_path TEXT,
    version INTEGER,
    spec_content TEXT,
    golden_set TEXT,
    score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    media_type TEXT DEFAULT 'text'
);
-- ── Graph read-model foundations ────────────────────────────────────────────
-- Nothing reads these yet; they land ahead of the read layer so the schema and
-- the code that uses it move in separate, revertible steps.

-- Materialized `/graph` payload. The graph only changes when a job writes to it,
-- so the payload is computed once and served cached; writers flip `dirty` and a
-- background task rebuilds. One logical row, id='current'.
CREATE TABLE IF NOT EXISTS graph_snapshot (
    id TEXT PRIMARY KEY,
    payload TEXT,
    built_at TIMESTAMP,
    entity_count INTEGER,
    edge_count INTEGER,
    dirty INTEGER DEFAULT 1
);

-- Materialized domain↔domain co-occurrence edges (domains sharing entities).
-- Computing one domain's neighbours live costs seconds on a large domain because
-- every entity-mention fans out to every document sharing that entity; the
-- snapshot build already computes the whole edge set, so this stores what it
-- found where a scoped read can seek it.
CREATE TABLE IF NOT EXISTS domain_edges (
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    weight REAL,
    PRIMARY KEY (source, target)
);
CREATE INDEX IF NOT EXISTS idx_domain_edges_source ON domain_edges(source);
CREATE INDEX IF NOT EXISTS idx_domain_edges_target ON domain_edges(target);

-- A COLLECTION is a labelled, hierarchical grouping of documents — a git repo, an
-- agent run, anything whose documents arrived together. It sits BESIDE `domains`,
-- not above or below: both are containers of documents, and they stay distinct
-- because their provenance differs. A domain is inferred (LLM-classified,
-- spec-cascaded); a collection is given (it is where the documents came from).
--
-- `kind` does not branch the schema. It selects which *asserted* edges an ingest
-- path writes (see collection_edges.type); the DERIVED edge — co-occurrence over
-- shared entities — comes free to every kind.
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    name TEXT,
    path TEXT UNIQUE,
    root_path TEXT,
    parent_path TEXT,
    document_count INTEGER DEFAULT 0,
    remote_url TEXT,
    commit_sha TEXT,
    kind TEXT DEFAULT 'git_repo',
    pos_x REAL,
    pos_y REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Membership + where the document sits in its collection's tree.
--
-- `role` and `emits_cooccurrence` are deliberately separate. Structural position
-- and extraction behaviour are independent: a root or group summary mentions
-- everything beneath it, so its co-occurrence is noise, but that is a default
-- rather than a law. Deriving one from the other forces every new collection kind
-- to impersonate a code repo to opt in.
CREATE TABLE IF NOT EXISTS document_collections (
    document_id TEXT NOT NULL REFERENCES documents(id),
    collection_id TEXT NOT NULL REFERENCES collections(id),
    parent_path TEXT,
    role TEXT,                              -- 'root' | 'group' | 'leaf'
    emits_cooccurrence INTEGER DEFAULT 1,   -- explicit, never inferred from role
    PRIMARY KEY (document_id, collection_id)
);
CREATE INDEX IF NOT EXISTS idx_document_collections_collection
    ON document_collections(collection_id);

-- Asserted collection→collection edges. `type` distinguishes them and is part of
-- the key: 'uses' (a declared dependency) and 'chain_next' (a trajectory).
-- `source`/`target` rather than from_/to_ so this matches `domain_edges` — the two
-- container kinds should not describe the same idea with different column names.
CREATE TABLE IF NOT EXISTS collection_edges (
    source TEXT NOT NULL REFERENCES collections(id),
    target TEXT NOT NULL REFERENCES collections(id),
    type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    PRIMARY KEY (source, target, type)
);
"""

def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    # One factory owns WAL + busy_timeout; init_db must not re-specify them.
    conn = get_connection(db_path)
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

    # entity_sources has no primary key, so without this the graph build's
    # per-entity source_count and the trade-route self-joins scan the whole table
    # — tens of seconds on a mid-size graph.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_sources_entity ON entity_sources(entity_id)")
    # Any domain-scoped read (a domain's docs, its entities, its neighbours) filters
    # on domain_path, but the only index is the composite PK (document_id,
    # domain_path), which cannot be seeked by path — so the planner falls back to
    # scanning.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_document_domains_path ON document_domains(domain_path)")
    # Seed the single snapshot row (dirty, empty) so a writer can flip the bit with a
    # plain UPDATE before the first build has ever run.
    conn.execute("INSERT OR IGNORE INTO graph_snapshot (id, dirty) VALUES ('current', 1)")
    conn.commit()
    conn.close()

def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def mark_graph_dirty(conn) -> None:
    """Flag the cached /graph snapshot for rebuild.

    Call after any write that changes the graph. Deliberately a plain UPDATE on a
    row seeded by init_db, so a writer never has to care whether a snapshot exists
    yet. Cheap enough to call unconditionally.
    """
    conn.execute("UPDATE graph_snapshot SET dirty = 1 WHERE id = 'current'")
