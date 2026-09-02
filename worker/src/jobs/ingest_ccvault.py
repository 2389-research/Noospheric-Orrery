# ABOUTME: Ingest ccvault agent-session archives into the graph (docs/ccvault-ingestion.md).
# ABOUTME: Flow A — summarize each session into a NEUTRAL agent_report doc, classify, extract_batch.
# ABOUTME: Flow B — extract graph-work (the #93 MCP tags), summarize, link BY ENTITY-ID (skip extract).

import hashlib
import json
import os
import uuid

from orrery_relay import Relay
from ..classifier import classify_document
from ..config import get_settings
from ..db import get_connection, mark_graph_dirty
from .ccvault_reader import (open_archive, list_sessions, session_transcript,
                             uses_orrery_graph, graph_work)

# Dedicated content types so extract_batch's session sweep never collides with the
# repo/tracker `code_intent` sweep. Flow B docs (active_work) are never extracted at all —
# they're linked by entity-id directly — so they carry a terminal status from the start.
SESSION_CONTENT_TYPE = "session_intent"
ACTIVE_WORK_CONTENT_TYPE = "active_work"
# Same fallback ingest_repo uses: a local model can return a payload with no usable
# primary_domain, and we must not crash the whole archive or write a null-path domain.
_UNCLASSIFIED_DOMAIN = "unclassified/needs-review"

_SUMMARY_INSTRUCTIONS = (
    "You are summarizing an AI coding-agent session for a knowledge graph. Write a NEUTRAL, "
    "factual summary of what the session worked on and did: the task, the areas / files / "
    "systems / topics touched, decisions made, and outcomes. Describe — do not evaluate, "
    "praise, rate, or criticize. No first person. Do not invent detail absent from the "
    "transcript. A few short paragraphs."
)

_ACTIVE_WORK_INSTRUCTIONS = (
    "You are recording, for a knowledge graph, the ANALYSIS an agent performed USING that graph "
    "in one session — so a later agent asking a similar question can read this instead of redoing "
    "the work. Write a NEUTRAL, factual summary: what was investigated (the questions/queries), "
    "what was found or concluded, and how the named entities relate. Describe — do not evaluate, "
    "praise, or criticize. No first person. Do not invent detail beyond the queries, results, and "
    "the agent's own synthesis provided. A few short paragraphs."
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
    resp = await relay.complete(model=model, max_tokens=1024,
                                messages=[{"role": "user", "content": prompt}])
    return (resp.text or "").strip()


async def _summarize_active_work(relay, model, meta: dict, work: dict, entity_names: list[str]) -> str:
    queries = "\n".join(f"- {name}({json.dumps(inp)[:160]})" for name, inp in work["tool_calls"]) or "(none captured)"
    ents = ", ".join(entity_names) if entity_names else "(none resolved)"
    prompt = (
        f"{_ACTIVE_WORK_INSTRUCTIONS}\n\n"
        f"Session project: {meta.get('project_path') or '(unknown)'}\n"
        f"Graph queries the agent ran:\n{queries}\n\n"
        f"Entities examined: {ents}\n\n"
        f"The agent's own synthesis:\n{work['synthesis'] or '(none)'}\n\n"
        "Neutral summary of the active work:"
    )
    resp = await relay.complete(model=model, max_tokens=1024,
                                messages=[{"role": "user", "content": prompt}])
    return (resp.text or "").strip()


def _resolve_entities(conn, entity_ids) -> list[str]:
    """Keep only ids that exist and are active in THIS workspace (the clone). Flow B links
    to these directly — ids that don't resolve (stale, or a different source noosphere) are
    dropped."""
    ids = [e for e in entity_ids if e]
    if not ids:
        return []
    out = []
    # chunk to stay under SQLite's variable limit
    for i in range(0, len(ids), 400):
        batch = ids[i:i + 400]
        ph = ",".join("?" * len(batch))
        rows = conn.execute(
            f"SELECT id FROM entities WHERE id IN ({ph}) AND invalid_at IS NULL", batch).fetchall()
        out.extend(r[0] for r in rows)
    return out


def _entity_names(conn, ids) -> dict:
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    return {r[0]: r[1] for r in conn.execute(
        f"SELECT id, canonical_name FROM entities WHERE id IN ({ph})", list(ids)).fetchall()}


def _upsert_domain(conn, dom):
    conn.execute("INSERT OR IGNORE INTO domains (id, path, parent_path, document_count) VALUES (?, ?, ?, 0)",
                 (str(uuid.uuid4()), dom, _parent_of(dom)))


async def run_ingest_ccvault(job: dict, db_path: str) -> None:
    """Flow A + Flow B over a staged ccvault archive, into the ACTIVE (clone) workspace.

    Per session: (A) if not yet summarized, write one neutral agent_report session doc; and
    (B) if it used the orrery graph and has unseen query_ids, write one active-work doc linked
    directly to the entity ids it touched. The two flows have independent watermarks
    (ccvault_sessions_seen / ccvault_processed), so a session Flow-A'd before Flow B existed
    still gets its active-work captured on a later pass. Each flow commits per session so a
    crash never leaves a watermark without its doc.
    """
    settings = get_settings()
    relay = Relay.from_settings(settings)
    config = json.loads(job["config"]) if job["config"] else {}
    archive_path = config["archive_path"]
    collection_id = config["collection_id"]
    spec_id = config["spec_id"]
    model = settings.classification_model

    arc = open_archive(archive_path)
    conn = get_connection(db_path)
    summarized = skipped_seen = flow_b_docs = flow_b_unanchored = 0
    try:
        seen = {r[0] for r in conn.execute("SELECT session_id FROM ccvault_sessions_seen")}
        processed = {r[0] for r in conn.execute("SELECT query_id FROM ccvault_processed")}
        taxonomy = [r[0] for r in conn.execute("SELECT path FROM domains")]

        for meta in list_sessions(arc):
            sid = meta["session_id"]

            # ── Flow A: neutral session summary ──────────────────────────────
            if sid in seen:
                skipped_seen += 1
            else:
                transcript = session_transcript(arc, sid)
                if not transcript.strip():
                    # Genuinely empty session (no user/assistant text) — nothing to summarize.
                    # Watermark so we don't keep re-reading it.
                    conn.execute("INSERT OR IGNORE INTO ccvault_sessions_seen (session_id) VALUES (?)", (sid,))
                    conn.commit()
                    seen.add(sid)
                else:
                    summary = await _summarize_session(relay, model, meta, transcript)
                    if not summary:
                        # Transient EMPTY MODEL OUTPUT (local models can return empty .text
                        # without raising). Do NOT watermark — let it retry on the next pass
                        # rather than permanently dropping the summary.
                        print(f"[ingest_ccvault] session {sid[:8]}: empty summary, will retry", flush=True)
                    else:
                        title = _session_title(meta)
                        cls = await classify_document(relay=relay, title=title, excerpt=summary[:4000],
                                                      existing_taxonomy=taxonomy, model=model)
                        dom = cls.get("primary_domain") or _UNCLASSIFIED_DOMAIN
                        if dom not in taxonomy:
                            taxonomy.append(dom)
                        doc_id = str(uuid.uuid4())
                        ch = hashlib.sha256(summary.encode()).hexdigest()
                        conn.execute(
                            "INSERT INTO documents (id, title, content, content_hash, source_path, "
                            "content_type, status, silo_id) VALUES (?, ?, ?, ?, ?, ?, 'classified', ?)",
                            (doc_id, title, summary, ch, f"ccvault:{sid}", SESSION_CONTENT_TYPE, collection_id))
                        conn.execute(
                            "INSERT INTO chunks (id, document_id, chunk_index, text, offset, length) "
                            "VALUES (?, ?, 0, ?, 0, ?)", (str(uuid.uuid4()), doc_id, summary, len(summary)))
                        # emits_cooccurrence=0: an agent_report doc is not neutral co-occurrence
                        # evidence. The silo gate already excludes it; this is defense-in-depth.
                        conn.execute(
                            "INSERT INTO document_collections (document_id, collection_id, parent_path, "
                            "role, emits_cooccurrence) VALUES (?, ?, NULL, 'leaf', 0)", (doc_id, collection_id))
                        conn.execute("UPDATE collections SET document_count = document_count + 1 WHERE id = ?",
                                     (collection_id,))
                        _upsert_domain(conn, dom)
                        conn.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, "
                                     "confidence) VALUES (?, ?, 1, 1.0)", (doc_id, dom))
                        conn.execute("UPDATE domains SET document_count = document_count + 1 WHERE path = ?", (dom,))
                        # Watermark in the SAME transaction as the doc (all-or-nothing).
                        conn.execute("INSERT OR IGNORE INTO ccvault_sessions_seen (session_id) VALUES (?)", (sid,))
                        conn.commit()
                        seen.add(sid)
                        summarized += 1

            # ── Flow B: active-work extraction (independent watermark) ────────
            if not uses_orrery_graph(arc, sid):
                continue
            work = graph_work(arc, sid)
            if not any(q not in processed for q in work["query_ids"]):
                continue  # nothing new for this session
            resolved = _resolve_entities(conn, work["entity_ids"])
            doc_id = None
            if resolved:
                names = _entity_names(conn, resolved)
                summary = await _summarize_active_work(relay, model, meta, work, list(names.values()))
                if not summary:
                    # Resolvable entities but transient EMPTY MODEL OUTPUT — do NOT record the
                    # query_ids as processed; retry next pass rather than losing the capture.
                    print(f"[ingest_ccvault] session {sid[:8]}: empty active-work summary, will retry", flush=True)
                    continue
                title = f"Active work — session {sid[:8]}"
                cls = await classify_document(relay=relay, title=title, excerpt=summary[:4000],
                                              existing_taxonomy=taxonomy, model=model)
                dom = cls.get("primary_domain") or _UNCLASSIFIED_DOMAIN
                if dom not in taxonomy:
                    taxonomy.append(dom)
                doc_id = str(uuid.uuid4())
                ch = hashlib.sha256(summary.encode()).hexdigest()
                # Terminal status + NO chunk: an active_work doc is anchored by entity-id,
                # not extracted, so it is never picked up by extract_batch and recalled only
                # through the entity channel (get_entity lists it among the entity's sources).
                conn.execute(
                    "INSERT INTO documents (id, title, content, content_hash, source_path, "
                    "content_type, status, silo_id) VALUES (?, ?, ?, ?, ?, ?, 'extracted', ?)",
                    (doc_id, title, summary, ch, f"ccvault-work:{sid}", ACTIVE_WORK_CONTENT_TYPE, collection_id))
                conn.execute(
                    "INSERT INTO document_collections (document_id, collection_id, parent_path, "
                    "role, emits_cooccurrence) VALUES (?, ?, NULL, 'leaf', 0)", (doc_id, collection_id))
                conn.execute("UPDATE collections SET document_count = document_count + 1 WHERE id = ?",
                             (collection_id,))
                _upsert_domain(conn, dom)
                conn.execute("INSERT INTO document_domains (document_id, domain_path, is_primary, "
                             "confidence) VALUES (?, ?, 1, 1.0)", (doc_id, dom))
                conn.execute("UPDATE domains SET document_count = document_count + 1 WHERE path = ?", (dom,))
                for eid in resolved:  # already a de-duplicated set of resolvable ids
                    conn.execute("INSERT INTO entity_sources (entity_id, document_id, extraction_pass) "
                                 "VALUES (?, ?, 'ccvault_flowb')", (eid, doc_id))
                flow_b_docs += 1
            if doc_id is None:
                flow_b_unanchored += 1  # graph-work seen but nothing resolved to anchor it
            # Mark every query_id in the segment (INSERT OR IGNORE — one row per id),
            # pointing at the doc it produced (NULL when unanchored) so re-ingest is a no-op.
            for q in work["query_ids"]:
                conn.execute("INSERT OR IGNORE INTO ccvault_processed (query_id, session_id, document_id) "
                             "VALUES (?, ?, ?)", (q, sid, doc_id))
                processed.add(q)
            conn.commit()

        # Phase 2: extract entities over session-summary docs. Gate on the DB, not the
        # in-memory counter: if a prior run committed session docs per-session but died
        # before this enqueue, those docs are durably 'classified' with no extraction job,
        # and a re-ingest (all sessions watermarked → summarized==0) would never repair
        # them. Enqueue whenever any session_intent doc is still 'classified'; a redundant
        # extract_batch is a harmless no-op (nothing left in scope). Flow B docs are excluded
        # (different content_type, already linked). Skip if one is already pending.
        stranded = conn.execute(
            "SELECT 1 FROM documents WHERE content_type = ? AND status = 'classified' LIMIT 1",
            (SESSION_CONTENT_TYPE,)).fetchone()
        pending = conn.execute(
            "SELECT 1 FROM jobs WHERE type = 'extract_batch' AND status IN ('queued','running') LIMIT 1"
        ).fetchone()
        if stranded and not pending:
            conn.execute(
                "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch', ?, 'queued', ?)",
                (str(uuid.uuid4()), collection_id, json.dumps({"spec_id": spec_id, "scope": SESSION_CONTENT_TYPE})))
        if summarized or flow_b_docs:
            mark_graph_dirty(conn)
        conn.commit()

        result = {"sessions_summarized": summarized, "sessions_skipped_seen": skipped_seen,
                  "active_work_docs": flow_b_docs, "active_work_unanchored": flow_b_unanchored}
        conn.execute("UPDATE jobs SET result = ? WHERE id = ?", (json.dumps(result), job["id"]))
        conn.commit()
        print(f"[ingest_ccvault] done: {summarized} session docs, {flow_b_docs} active-work docs "
              f"({flow_b_unanchored} unanchored), {skipped_seen} sessions already seen", flush=True)
    finally:
        conn.close()
        arc.close()
