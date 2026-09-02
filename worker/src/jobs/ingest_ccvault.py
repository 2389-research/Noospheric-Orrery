# ABOUTME: Ingest ccvault agent-session archives into the graph (docs/ccvault-ingestion.md).
# ABOUTME: Flow A: recursively summarize each session into a NEUTRAL agent_report doc, classify,
# ABOUTME: enqueue extract_batch. Flow B (active-work extraction from the #93 MCP tags) is a follow-up.

import hashlib
import json
import os
import uuid

from orrery_relay import Relay
from ..classifier import classify_document
from ..config import get_settings
from ..db import get_connection, mark_graph_dirty
from .ccvault_reader import open_archive, list_sessions, session_transcript

# Dedicated content_type so extract_batch's session-scoped sweep never collides with the
# repo/tracker `code_intent` sweep (and vice-versa).
SESSION_CONTENT_TYPE = "session_intent"

_SUMMARY_INSTRUCTIONS = (
    "You are summarizing an AI coding-agent session for a knowledge graph. Write a NEUTRAL, "
    "factual summary of what the session worked on and did: the task, the areas / files / "
    "systems / topics touched, decisions made, and outcomes. Describe — do not evaluate, "
    "praise, rate, or criticize. No first person. Do not invent detail absent from the "
    "transcript. A few short paragraphs."
)


def _parent_of(domain_path):
    if not domain_path or "/" not in domain_path:
        return None
    return domain_path.rsplit("/", 1)[0]


def _session_title(meta: dict) -> str:
    sid = meta["session_id"]
    proj = meta.get("project_path") or ""
    base = os.path.basename(proj.rstrip("/")) if proj else ""
    return f"Session {sid[:8]} — {base}" if base else f"Session {sid[:8]}"


async def _summarize_session(relay, model, meta: dict, transcript: str) -> str:
    prompt = (
        f"{_SUMMARY_INSTRUCTIONS}\n\n"
        f"Session project: {meta.get('project_path') or '(unknown)'}\n"
        f"Started: {meta.get('started_at')}\n\n"
        f"TRANSCRIPT (user/assistant turns, chronological):\n{transcript}\n\n"
        "Neutral summary:"
    )
    resp = await relay.complete(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.text or "").strip()


async def run_ingest_ccvault(job: dict, db_path: str) -> None:
    """Flow A. Summarize each not-yet-seen ccvault session into one neutral agent_report
    document, classify it, and enqueue a session-scoped extract_batch. Per-session atomic:
    a session's document + its `ccvault_sessions_seen` ledger row commit together, so a crash
    never leaves a session marked-seen-without-a-doc (skipped forever) or doc-without-ledger
    (duplicated on re-ingest)."""
    settings = get_settings()
    relay = Relay.from_settings(settings)
    config = json.loads(job["config"]) if job["config"] else {}
    archive_path = config["archive_path"]
    collection_id = config["collection_id"]
    spec_id = config["spec_id"]

    arc = open_archive(archive_path)
    conn = get_connection(db_path)
    summarized = 0
    skipped_seen = 0
    try:
        seen = {r[0] for r in conn.execute("SELECT session_id FROM ccvault_sessions_seen").fetchall()}
        taxonomy = [r[0] for r in conn.execute("SELECT path FROM domains").fetchall()]

        for meta in list_sessions(arc):
            sid = meta["session_id"]
            if sid in seen:
                skipped_seen += 1
                continue

            transcript = session_transcript(arc, sid)
            summary = ""
            if transcript.strip():
                summary = await _summarize_session(relay, settings.classification_model, meta, transcript)

            if not summary:
                # Nothing to ingest (empty / tool-only session). Mark seen so re-ingest
                # doesn't keep re-summarizing it, and move on.
                conn.execute("INSERT OR IGNORE INTO ccvault_sessions_seen (session_id) VALUES (?)", (sid,))
                conn.commit()
                seen.add(sid)
                continue

            title = _session_title(meta)
            cls = await classify_document(
                relay=relay, title=title, excerpt=summary[:4000],
                existing_taxonomy=taxonomy, model=settings.classification_model,
            )
            dom = cls["primary_domain"]
            if dom not in taxonomy:
                taxonomy.append(dom)

            doc_id = str(uuid.uuid4())
            content_hash = hashlib.sha256(summary.encode()).hexdigest()
            # silo_id set EXPLICITLY to the ccvault collection (agent_report). The gate in
            # recompute_cooccurrence keys on documents.silo_id -> silo_kind.kind, and for a
            # gated kind we do not rely on init_db's implicit backfill timing (see design doc).
            conn.execute(
                "INSERT INTO documents (id, title, content, content_hash, source_path, "
                "content_type, status, silo_id) VALUES (?, ?, ?, ?, ?, ?, 'classified', ?)",
                (doc_id, title, summary, content_hash, f"ccvault:{sid}",
                 SESSION_CONTENT_TYPE, collection_id),
            )
            conn.execute(
                "INSERT INTO chunks (id, document_id, chunk_index, text, offset, length) "
                "VALUES (?, ?, 0, ?, 0, ?)",
                (str(uuid.uuid4()), doc_id, summary, len(summary)),
            )
            conn.execute(
                "INSERT INTO document_collections (document_id, collection_id, parent_path, "
                "role, emits_cooccurrence) VALUES (?, ?, NULL, 'leaf', 1)",
                (doc_id, collection_id),
            )
            conn.execute("UPDATE collections SET document_count = document_count + 1 WHERE id = ?",
                         (collection_id,))
            conn.execute(
                "INSERT OR IGNORE INTO domains (id, path, parent_path, document_count) VALUES (?, ?, ?, 0)",
                (str(uuid.uuid4()), dom, _parent_of(dom)),
            )
            conn.execute(
                "INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) "
                "VALUES (?, ?, 1, 1.0)", (doc_id, dom),
            )
            conn.execute("UPDATE domains SET document_count = document_count + 1 WHERE path = ?", (dom,))
            # Same transaction as the doc — the atomicity guarantee above.
            conn.execute("INSERT OR IGNORE INTO ccvault_sessions_seen (session_id) VALUES (?)", (sid,))
            conn.commit()
            seen.add(sid)
            summarized += 1
            print(f"[ingest_ccvault] session {sid[:8]} -> {dom} (doc {doc_id[:8]})", flush=True)

        if summarized:
            # Phase 2: extract entities over the new session docs only.
            conn.execute(
                "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch', ?, 'queued', ?)",
                (str(uuid.uuid4()), collection_id,
                 json.dumps({"spec_id": spec_id, "scope": SESSION_CONTENT_TYPE})),
            )
            mark_graph_dirty(conn)
            conn.commit()

        result = {"sessions_summarized": summarized, "sessions_skipped_seen": skipped_seen}
        conn.execute("UPDATE jobs SET result = ? WHERE id = ?", (json.dumps(result), job["id"]))
        conn.commit()
        print(f"[ingest_ccvault] done: {summarized} summarized, {skipped_seen} already seen", flush=True)
    finally:
        conn.close()
        arc.close()
