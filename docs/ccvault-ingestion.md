# ccvault ingestion — design

Status: **design / not built**. Consumes [ccvault](https://github.com/2389-research/ccvault)
session archives as an Orrery source, the same way repos and the Obsidian vault are sources.

## Why this exists

Orrery captures **passive work** (documents, code, tracker runs) well. It does not capture
**active work** — the one-off analysis an agent does *using* the graph — which today is lost
unless the user self-reports it. ccvault archives agent sessions (Claude Code / Codex) verbatim.
By ingesting those archives, Orrery can:

1. learn from what agents have been doing generally (a corpus of session summaries), and
2. **close the loop**: detect where an agent worked *against the Orrery graph* (via the MCP tags
   from #93) and turn that into retrievable content, so the next agent asking a similar question
   **retrieves the prior work instead of redoing it**.

This is the follow-on to #93 (which made the MCP emit `[query:…]`/`[entity:…]`/`[doc:…]`/`[image:…]`
tags) and to the validated finding that ccvault persists those tags in `turns.raw_json`.

## Boundary rule (important)

**The dependency points Orrery → ccvault, never the reverse.** ccvault is a general-purpose,
neutral archive used by things other than Orrery; it already stores the complete, untruncated
`raw_json`, which is all a consumer needs. **Orrery does 100% of the Orrery-specific work** (tag
parsing, slicing, summarizing) at ingest time. We do **not** add Orrery semantics (a tag index, a
schema for our tags) to ccvault. This mirrors the `orrery-office-display` boundary: talk to the
other system only through its neutral surface, never fork or adapt it to our use case.

Orrery reads ccvault's archive through its neutral surface: the SQLite `turns` (`raw_json`,
`content`, `session_id`, `type`, `timestamp`) and `tool_uses` (`tool_name`, `turn_id`,
`session_id`) tables, or an equivalent ccvault export. `raw_json` is the full-fidelity source;
the truncated `content`/FTS column is only a preview and is **not** used for extraction.

## Target: a COPY of the source noosphere (this is the crux)

Entity ids are workspace-local: `entities.id` is a per-workspace UUID and each noosphere is its
own SQLite DB. The `[entity:…]` ids in a session's logs refer to the noosphere the agent was
**querying**. Ingesting that work into an *empty* sandbox would leave those ids dangling and the
retrieval loop unclosed (a later agent queries its own graph, where the artifact isn't present).

**Resolution: clone the source noosphere and run the flows into the clone.** Because the clone is
a copy of the same DB, the `[entity:…]` ids resolve there, Flow B links directly to real nodes,
and retrieval closes *inside the clone* — while the **formal/full noospheres are left untouched**.

- Phase 1 mechanic: a workspace is a DB file at `{data_dir}/workspaces/{ws_id}/orrery.db`
  (`repositories/factory.py`). "Copy a noosphere" = create a new workspace id and copy that file
  (offline copy; the source is read-only during it). `/ingest/ccvault` then targets the clone.
- The clone is a **snapshot** and will diverge from the evolving source — fine for phase-1 testing,
  and the point: you evaluate the ingested active-work in isolation before anything formal changes.
- This seeds the longer-term model: **multiple interlinking noospheres** — smaller/specific ones
  that feed the larger main ones by *reference* (not copy). Promotion / cross-noosphere references
  are future work; phase 1 is a snapshot clone.

**Clone hygiene (required — the copy is not inert).** The worker auto-discovers *every*
`workspaces/*/orrery.db` and runs their due `watched_sources` scans and any queued/orphaned `jobs`
(`worker/src/main.py`). A raw copy therefore inherits the source's watched sources and would keep
re-syncing repos/vaults *into the clone* and running inherited jobs — so it stops being a controlled
snapshot. After copying, the clone-creation step MUST: disable/delete `watched_sources` rows and
delete non-terminal `jobs` rows in the clone, leaving only the ccvault ingest to run there.

**Retrieval isolation (prerequisite, not a data issue).** The search index is currently
**process-global, not workspace-keyed** (`pipeline.py` `_indexes_ready`; `retrieval.py` `_entity_view`),
while requests route to a workspace by `X-Workspace-Id`. So one process serving multiple workspaces
can answer a clone query from another workspace's cached index. For Flow B's retrieval loop to
actually close, **the clone must be served by an orchestrator process serving only the clone** (a
throwaway instance pointed at the clone's data dir) — or the per-workspace-index fix must land first.
This is a pre-existing multi-workspace limitation, called out here because Flow B's demo depends on it.

Both flows write into the clone. Which source noosphere a given session queried is recoverable from
its log (`select_noosphere` / the workspace it used), so the operator clones the right one; a
session whose queried workspace ≠ the clone is skipped by Flow B (its ids wouldn't resolve).

## Provenance

Both flows write **`agent_report`** silo documents. An `agent_report` is an agent's account of its
own activity — not neutral evidence of what co-occurs — so per the silo model its documents are
**excluded from co-occurrence edge emission** (`recompute_cooccurrence`, gated at `db.py:930` on
`silo_kind.kind != 'agent_report'`). They are retrievable, entity-anchored content, not a source of
new graph structure. So even though the flows write into a clone of a real graph, they add
**retrievable docs without mutating graph structure**.

Add a `ccvault` key to `FLOW_DEFAULT_KIND` → `agent_report`. **This map is mirrored byte-identical
between `worker/src/silo.py` and `orchestrator/src/pipeline/silo.py`** (enforced by
`orchestrator/tests/test_schema_mirror.py`) — the key must be added to both. `collections.create`
resolves `resolve_kind(flow_default_kind("ccvault"), override)`, and `backfill_provenance_kind`
derives from the same map, so both paths get `agent_report` for free once the key exists.

## The two flows

One ingest trigger runs both, over the sessions in the staged artifact, into the clone.

### Flow A — session summarization (the tracker-run analogue)

A Claude Code session has internal structure (turn clusters, tool calls, results), like a tracker
run has rounds/steps. So a session plays the structural role a repo/run plays — it is
**recursively summarized** (turn-clusters → per-cluster summary → session summary). This is a
*pattern* borrowed from codesum/tracksum (bounded, non-agentic relay summarization with the
extraction model, **neutral / no judgment**), **not** a reuse of their code — codesum summarizes a
filesystem and tracksum summarizes tracker activity; neither understands ccvault turn-clusters, so
Flow A needs new session-summarization code in that shape.

- Output: `agent_report` documents (a dedicated `content_type`, e.g. `session_intent`), classified
  via `classify_document`, then `extract_batch` enqueued scoped to that content_type — identical
  downstream to `ingest_tracker_runs`, but **not** sharing the repo/tracker `code_intent` scope
  (so an unrelated repo ingest's batch never sweeps ccvault docs, and vice-versa).
- Dedup unit: the **session** (has this session already been summarized in this clone?).

Scope of Flow A is deliberately open — we cannot predict what a session contains, so early testing
runs it into the clone and filters later (by project, size, or excluding pure-debugging sessions).

### Flow B — active-work extraction (the recursive graph loop)

Within the same pass, detect the segments where the agent worked **against the Orrery graph** and
turn each into an entity-anchored artifact.

- **Detect:** sessions/turns whose `tool_uses.tool_name` is `mcp__noospheric-orrery__*`, and whose
  `raw_json` carries `[query:…]` tags.
- **Slice the unit of work:** `tool_use → tool_result → the following assistant turns` where the
  agent synthesized from the results (the slice `pipeline_extract.py` proved out).
- **Record ids:** parse `[query:qry_…]`, `[entity:…]`, `[doc:…]`, `[image:…]` from `raw_json` by
  **reserved prefix** (per the #93 contract; do not match arbitrary `[...]`, since titles are
  printed bracketed). Alternation: `\[(query|entity|doc|image):([^\]]+)\]`.
- **Summarize neutrally:** an "active work" summary of what the agent learned/did with the graph.
- **Anchor by DIRECT entity-id link, not re-extraction.** We already hold the exact `[entity:…]`
  ids, and they resolve in the clone (it's a copy of the queried graph). So the Flow B doc attaches
  to those existing nodes directly (write `entity_sources` rows linking the new doc to the known
  entity ids) — it must **not** go through `extract_batch`, which would mint fresh silo-local
  entities and, under silo-scoped normalization, never link back to the originals. Ids that don't
  resolve in the clone (stale/deleted, or a different source workspace) are dropped with a note.
- **Store:** an `agent_report` document, linked to the resolved entity ids. Give it a **terminal
  `status`** after linking (`documents.create` defaults `status='pending'`; a Flow B doc skips
  extraction, so set it complete explicitly or it lingers `pending` and skews status counts).

**How Flow B docs are recalled — entity channel only.** A link-only doc (no chunks) surfaces
through the **entity** path: search returns the entity → `get_entity` lists the doc among its
sources → the agent reads it. It does **not** surface via semantic/chunk similarity to the summary
text (Flow B creates no chunks, and the "relevant excerpts" block is chunk-backed). So the loop is:
similar query → same entities → prior active-work doc. If we later want the summary text itself to
be semantically searchable, Flow B would also need to chunk+embed the summary (deferred).

Note: linking a Flow B doc to a pre-existing formal entity adds the `ccvault`/`agent_report` silo to
that entity's silo membership (its `entity_sources` gains a row whose doc has `silo_id=ccvault`).
Benign in a throwaway clone (co-occurrence stays gated; `silo_match` is NULL-safe), but noted.

**Trigger condition — unseen `query_id`.** Flow B runs for a graph-work segment **only if its
`query_id` has not already been ingested in this clone.** `query_id` is unique per MCP call
(`qry_{uuid4().hex}`), so this is the natural incremental key — re-ingesting the same session is a
no-op (all query_ids seen) and only genuinely new graph work is captured. Same discipline the
watched-source sync uses (repos skip on unchanged `commit_sha`; vault docs on `source_path`/mtime).

## Dedup state (per workspace/clone)

```sql
CREATE TABLE IF NOT EXISTS ccvault_processed (
  query_id    TEXT NOT NULL,      -- Flow B dedup key (one row per query_id in a segment)
  session_id  TEXT NOT NULL,
  document_id TEXT,               -- the agent_report doc this segment produced
  ingested_at TEXT NOT NULL,
  PRIMARY KEY (query_id)
);
CREATE TABLE IF NOT EXISTS ccvault_sessions_seen (
  session_id  TEXT PRIMARY KEY,   -- Flow A watermark
  ingested_at TEXT NOT NULL
);
```

- A synthesis segment may reference several `query_id`s; write **one `ccvault_processed` row per
  query_id**, all pointing at the same `document_id`. A segment is "new" if **any** of its
  query_ids is unseen; already-seen query_ids in that segment are not re-processed.
- Tables added to **both** `db.py` files **and** to `_MIRRORED_TABLES` in
  `orchestrator/tests/test_schema_mirror.py` (else CI fails). Opened via `get_connection` (WAL).
- (The two ledgers could be unified later; kept separate for clarity of the two watermarks.)

## Mechanics / invariants

- **`silo_id` is set explicitly to `collection_id` on every insert.** The agent_report co-occurrence
  gate keys on `documents.silo_id → silo_kind.kind`; the existing repo/tracker jobs leave `silo_id`
  NULL and rely on `init_db`'s `backfill_silo_ids` running before `extract_batch` in a later poll —
  implicit timing that is load-bearing only for gated kinds. For ccvault (agent_report) do not rely
  on it: pass `silo_id=collection_id` to `documents.create` (it already accepts it).
- **One persistent ccvault collection per archive per clone**, not one per session (a per-session
  collection would make every session its own silo and isolate normalization per session). Sessions
  are **documents** within that one collection/silo. `/ingest/ccvault` is **idempotent** on it —
  reuse the existing collection rather than creating a new UNIQUE-`path` row (which would 409 like
  `/ingest/repo` does); incrementality comes from the ledgers, not from a fresh collection.
  Get-or-create has a TOCTOU: `collections.path` is UNIQUE, so two concurrent creates race to a 500.
  Wrap create in a `try/except IntegrityError → re-get_by_path` (single-operator phase 1 makes the
  race unlikely, but the route claims idempotency, so handle it).
- **`entity_sources` has no uniqueness constraint**, so Flow B linking the same entity twice in one
  segment would write duplicate rows; de-dup the entity-id set per segment before linking.
- **Per-session atomicity:** summarize a session fully (many relay calls), then commit its docs +
  its ledger rows in **one transaction**. Never one giant transaction over the whole archive, and
  never ledger-before-doc (a crash would permanently skip a session/query or duplicate on re-ingest).

## Entry points

Two-phase, mirroring `POST /ingest/repo` and `POST /ingest/tracker-runs`:

- **`POST /ingest/ccvault`** (orchestrator, `routes/ingest.py`): validates the staged artifact path
  and target workspace (the clone), gets-or-creates the workspace's ccvault `collections` row
  (`kind="ccvault"`, provenance defaulting to `agent_report`), and enqueues an `ingest_ccvault`
  job. Returns `{job_id, collection_id}`. Request model beside `RepoIngestRequest` in `models.py`.
- **`worker/src/jobs/ingest_ccvault.py`** (`run_ingest_ccvault`): opens the staged ccvault archive;
  iterates sessions; per session runs Flow A (summarize → docs → classify) and Flow B (detect
  graph-work, skip seen query_ids, summarize → doc → direct entity_sources links); commits docs +
  ledger per session; `mark_graph_dirty`; enqueues `extract_batch` **scoped to the session-intent
  content_type** (Flow A only — Flow B docs are pre-linked and skip extraction). Registered in the
  worker poll loop / `runner.py` dispatch like the other `ingest_*` jobs.

## Source model & phasing

The staged artifact is ccvault's own output — a `ccvault.db` (or export) copied to a staging path,
e.g. `/data/ccvault/<label>/` — exactly as repos stage at `/data/repos/*` and the vault at
`/data/vault`. The delivery mechanism evolves; the featurizer does not:

1. **Now — manual one-off.** Clone the relevant noosphere, stage the artifact, call `/ingest/ccvault`.
2. **Later — watched source.** Wrap as a `watched_sources` row scanned on a cadence (reuse
   `scan_source`/`sync_repo` machinery) so new sessions ingest automatically.
3. **Eventually — shared archive.** A shared, git-synced "ccvault vault" many people push sessions
   to; Orrery populates from the shared store. Only *where the artifact is staged from* changes.

## What we are NOT doing

- No changes to ccvault (no tag index, no schema for our tags, no cap change). It stays neutral.
- No watched-source auto-sweep in phase 1 (manual one-off first).
- No writes to formal/full noospheres — flows run only into a clone.
- No cross-noosphere promotion / interlink references yet (future).
- No org-wide / multi-user capture yet (single operator); a consent/scope stance is required before
  broadening (flagged in #93). The staging-location model makes this a delivery concern.

## Open questions

1. **Flow A granularity** — one summary doc per session, or per turn-cluster with a session
   roll-up? Affects retrieval granularity and `extract_batch` load.
2. **Flow B slice boundaries** — how many turns after a `tool_result` count as "the work" (until the
   next unrelated tool_use / user turn, vs. an LLM boundary call).
3. **Clone freshness** — a snapshot diverges from the evolving source. For phase-1 testing that's
   intended; the eventual interlink model (references, not copies) is how this stops being a
   snapshot. Out of scope for phase 1.
4. **Codex sessions** — ccvault marks `source = codex`; its tool-call shape differs. Phase 1 targets
   CC-shaped sessions; Codex detection is later.
5. **Staging format** — a copied `ccvault.db` (read SQLite directly, highest fidelity via `raw_json`)
   vs. a ccvault export (more portable for the future shared-archive phase).
