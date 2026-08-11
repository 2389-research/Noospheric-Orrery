import sqlite3
import os
import time
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

# repos/* -> collections/*. Applied BEFORE the schema script (see migrate_to_collections).
_LEGACY_TABLES = [
    ("repos", "collections"),
    ("document_repos", "document_collections"),
    ("repo_edges", "collection_edges"),
]
_LEGACY_COLUMNS = [
    ("document_collections", "repo_id", "collection_id"),
    ("collection_edges", "from_repo", "source"),
    ("collection_edges", "to_repo", "target"),
]


def migrate_to_collections(conn) -> None:
    """Rename the repo-era tables and columns in place.

    MUST run BEFORE `executescript(SCHEMA)`. `CREATE TABLE IF NOT EXISTS collections`
    would otherwise create an EMPTY table beside the populated `repos`, the rename
    would then fail with "table collections already exists", and every existing corpus
    would be stranded behind an empty one — silently, since reads would just return
    nothing.

    `ALTER TABLE ... RENAME TO` also rewrites REFERENCES clauses in other tables
    (SQLite >= 3.25 with legacy_alter_table off, the default), so the foreign keys
    follow automatically. Idempotent: each step is skipped once it has been applied.

    ATOMIC. SQLite makes DDL transactional, so the whole sequence runs inside a
    savepoint: a failure part-way through would otherwise leave one table renamed and
    the next not — exactly the half-migrated state the preflight below refuses to
    start from, reached by a different route and with no way to retry out of it.

    The write lock is taken UP FRONT with BEGIN IMMEDIATE, not lazily. The orchestrator
    and the worker both open every workspace, so they genuinely race on a legacy
    database's first open. A deferred transaction would let both read the legacy schema,
    and the second one to attempt a write would get SQLITE_BUSY_SNAPSHOT when upgrading
    its now-stale read snapshot — a failure `busy_timeout` cannot rescue, because
    waiting does not make an outdated snapshot current. BEGIN IMMEDIATE makes the
    contention happen at the lock instead, where busy_timeout does apply, so the loser
    waits and then observes the migrated schema rather than failing.
    """
    # If a transaction is already open (a caller mid-write), the savepoint alone is
    # correct — and BEGIN would raise. Only take the lock when we are the outermost.
    started = not conn.in_transaction
    if started:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute("SAVEPOINT collections_migration")
    try:
        _migrate_to_collections(conn)
    except Exception:
        conn.execute("ROLLBACK TO collections_migration")
        conn.execute("RELEASE collections_migration")
        if started:
            conn.rollback()
        raise
    conn.execute("RELEASE collections_migration")
    if started:
        # Commit here rather than leaving the write open: init_db keeps running
        # (executescript, ALTERs) and holding the lock across all of it would widen
        # the window the other process has to wait through.
        conn.commit()


def _migrate_to_collections(conn) -> None:
    """The migration body. Always call `migrate_to_collections`, which makes it atomic."""
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    # PREFLIGHT every pair before touching anything. Raising mid-loop would leave the
    # database half-renamed — one table moved, the next not — which is a worse state
    # than the one being refused, and init_db would fail identically on every retry.
    conflicts = [(old, new) for old, new in _LEGACY_TABLES
                 if old in tables and new in tables]
    if conflicts:
        # Rows live under each name and the schema script is about to make the new
        # name authoritative, silently orphaning everything still under the old one.
        # No safe automatic merge exists (ids can collide), so stop loudly.
        pairs = ", ".join(f"{o!r}+{n!r}" for o, n in conflicts)
        raise RuntimeError(
            f"cannot migrate: both names exist for {pairs}. Rows under the old name "
            f"would become unreachable. Merge them by hand, then drop the old table.")
    for old, new in _LEGACY_TABLES:
        if old in tables and new not in tables:
            conn.execute(f"ALTER TABLE {old} RENAME TO {new}")
            tables.discard(old)
            tables.add(new)
    for table, old_col, new_col in _LEGACY_COLUMNS:
        if table not in tables:
            continue
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if old_col in cols and new_col not in cols:
            conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO {new_col}")
    # The index survives the table rename but keeps its old NAME; the schema script
    # recreates it as idx_document_collections_collection.
    conn.execute("DROP INDEX IF EXISTS idx_document_repos_repo")
    # The stored discriminator followed the tables. `repo_uses` was the repo-era name
    # for what the contract has always exposed as `uses`; writers now emit `uses`
    # directly. Idempotent — a second pass matches nothing.
    # Guarded: this runs BEFORE the schema script, so on a fresh database the table
    # does not exist yet — and there is nothing to migrate there anyway.
    if "collection_edges" in tables:
        # A pair can carry BOTH spellings after a mixed-version deploy (one process
        # writing `repo_uses`, another `uses`). A bare UPDATE then violates the
        # composite key (source, target, type) and init_db raises — the database stops
        # opening at all. So fold the duplicates first, keeping the larger weight,
        # then rewrite what is left.
        conn.execute("""UPDATE collection_edges SET weight = MAX(weight, (
                            SELECT r.weight FROM collection_edges r
                            WHERE r.source = collection_edges.source
                              AND r.target = collection_edges.target
                              AND r.type = 'repo_uses'))
                        WHERE type = 'uses' AND EXISTS (
                            SELECT 1 FROM collection_edges r
                            WHERE r.source = collection_edges.source
                              AND r.target = collection_edges.target
                              AND r.type = 'repo_uses')""")
        conn.execute("""DELETE FROM collection_edges WHERE type = 'repo_uses' AND EXISTS (
                            SELECT 1 FROM collection_edges r
                            WHERE r.source = collection_edges.source
                              AND r.target = collection_edges.target
                              AND r.type = 'uses')""")
        conn.execute("UPDATE collection_edges SET type = 'uses' WHERE type = 'repo_uses'")




def _migrate_collection_columns(conn) -> None:
    """Bring a RENAMED legacy collection table up to the current column set.

    `migrate_to_collections` moves `repos` -> `collections`, but a renamed table keeps
    its old COLUMNS, and `CREATE TABLE IF NOT EXISTS` adds none to a table that already
    exists. So a legacy corpus arrives with the right table names and the wrong shape,
    and the reads that select `role` or filter `emits_cooccurrence` fail on it — or
    worse, a column added with a DEFAULT reads as though it had been chosen.

    Must run AFTER the schema script (the tables have to exist on a fresh database).
    Idempotent: every step is guarded on the column being absent.
    """
    coll_cols = {r[1] for r in conn.execute("PRAGMA table_info(collections)").fetchall()}
    for col, decl in [("pos_x", "REAL"), ("pos_y", "REAL"),
                      ("remote_url", "TEXT"), ("commit_sha", "TEXT")]:
        if col not in coll_cols:
            conn.execute(f"ALTER TABLE collections ADD COLUMN {col} {decl}")
    # `kind` discriminates a git repo from a tracker run. Legacy corpora predate it and
    # `remote_url IS NULL` is not a proxy (a locally-ingested repo has it NULL too).
    if "kind" not in coll_cols:
        conn.execute("ALTER TABLE collections ADD COLUMN kind TEXT DEFAULT 'git_repo'")
        conn.execute("UPDATE collections SET kind = 'git_repo' WHERE kind IS NULL")
    # Recover the kind of collections ingested before that column existed.
    # `chain_next` is written by exactly one code path — tracker-run ingest — so
    # participating in such an edge is a fact about provenance, not a guess. Defaulting
    # these to 'git_repo' would mislabel an entire trajectory corpus on first open.
    # Limitation: a corpus of ONE run has no chain edge and stays 'git_repo'. Partial
    # recovery beats none, and re-ingesting sets `kind` directly.
    conn.execute("""UPDATE collections SET kind = 'tracker_run'
                    WHERE kind = 'git_repo' AND id IN (
                        SELECT source FROM collection_edges WHERE type = 'chain_next'
                        UNION
                        SELECT target FROM collection_edges WHERE type = 'chain_next')""")

    # `role` + `emits_cooccurrence` replaced the overloaded `level`, which did three
    # unrelated jobs: structural position, a co-occurrence switch (`level == 'file'`),
    # and the lookup key for a collection's own summary doc.
    dc_cols = {r[1] for r in conn.execute("PRAGMA table_info(document_collections)").fetchall()}
    added: list[str] = []
    if "role" not in dc_cols:
        conn.execute("ALTER TABLE document_collections ADD COLUMN role TEXT")
        added.append("role")
    if "emits_cooccurrence" not in dc_cols:
        conn.execute("ALTER TABLE document_collections ADD COLUMN emits_cooccurrence INTEGER DEFAULT 1")
        added.append("emits_cooccurrence")
    # Only a MIGRATED table has `level`; this schema never creates it, so the backfill
    # is guarded on the column's presence rather than assuming it (the fork's version
    # could assume it — its schema still declared the column — and copying that
    # verbatim would raise "no such column: level" on every fresh database).
    # Derive ONLY the columns this call actually added. `level` stays populated on
    # legacy rows forever, so a backfill gated on `level IS NOT NULL` alone would re-run
    # on every open and RESET these two columns from the stale legacy value — silently
    # reverting anything written since. That is not hypothetical: `emits_cooccurrence`
    # exists precisely so it can be set independently of structural role, and a legacy
    # row would have been pinned to the level-derived value permanently, undoing an
    # operator fix or a re-ingest on the next process start.
    #
    # Running only for freshly-added columns also makes this a true one-shot: after the
    # first open the columns exist, `added` is empty, and no UPDATE runs at all.
    _CASE = {
        "role": """CASE level
                       WHEN 'repo' THEN 'root'
                       WHEN 'module' THEN 'group'
                       WHEN 'file' THEN 'leaf'
                   END""",
        # `level == 'file'` is what the old co-occurrence guard tested.
        "emits_cooccurrence": "CASE WHEN level = 'file' THEN 1 ELSE 0 END",
    }
    # Only a MIGRATED table has `level`; this schema never creates it, so this is guarded
    # on the column's presence rather than assuming it (the fork's version could assume
    # it — its schema still declared the column — and copying that verbatim raises
    # "no such column: level" on every fresh database).
    if added and "level" in dc_cols:
        sets = ", ".join(f"{col} = {_CASE[col]}" for col in added)
        conn.execute(f"UPDATE document_collections SET {sets} WHERE level IS NOT NULL")


def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    # One factory owns WAL + busy_timeout; init_db must not re-specify them.
    conn = get_connection(db_path)
    migrate_to_collections(conn)   # MUST run BEFORE the schema script — see above
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

    _migrate_collection_columns(conn)

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

def _enable_wal(conn: sqlite3.Connection, attempts: int = 6) -> None:
    """Put the connection's database into WAL mode, tolerating a concurrent switcher.

    Changing journal mode needs an exclusive moment, and `busy_timeout` does NOT
    reliably cover it — setting the timeout first (which this still does, and must) was
    necessary but not sufficient. Two processes opening the same not-yet-WAL file, or one
    opening while another holds a write transaction on it, can still get SQLITE_BUSY
    here. Both services open every workspace on startup, so that is the normal case for
    a freshly imported database, not an exotic one.

    Retries briefly, and treats "already WAL" as success: if another process won the
    race, the work is done and there is nothing left to do. Only a persistent failure
    propagates, because operating in rollback-journal mode would silently drop the
    concurrency guarantee the rest of this codebase assumes.
    """
    for attempt in range(attempts):
        try:
            row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            if row and str(row[0]).lower() == "wal":
                return
        except sqlite3.OperationalError as e:
            # Only contention is retryable; a genuine problem (an unwritable file, say)
            # must surface now rather than after six pointless sleeps.
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
        # Someone else may have completed the switch while we were blocked.
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            if row and str(row[0]).lower() == "wal":
                return
        except sqlite3.OperationalError:
            pass
        time.sleep(0.05 * (attempt + 1))
    # Out of attempts: let the real error speak instead of reporting a clean connection
    # that is not actually in WAL.
    conn.execute("PRAGMA journal_mode=WAL")


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # busy_timeout FIRST. Switching journal modes takes a brief exclusive lock, so on a
    # database not yet in WAL — a fresh file, or an imported one — this pragma is itself
    # a contended write. Set after, it ran with NO timeout in force and raised "database
    # is locked" immediately whenever another process was opening the same file, which
    # both services do on startup. Ordering is the whole fix: a pragma cannot be covered
    # by a timeout that has not been set yet.
    conn.execute("PRAGMA busy_timeout=5000")
    _enable_wal(conn)
    return conn


def mark_graph_dirty(conn) -> None:
    """Flag the cached /graph snapshot for rebuild.

    Call after any write that changes the graph. Deliberately a plain UPDATE on a
    row seeded by init_db, so a writer never has to care whether a snapshot exists
    yet. Cheap enough to call unconditionally.
    """
    conn.execute("UPDATE graph_snapshot SET dirty = 1 WHERE id = 'current'")
