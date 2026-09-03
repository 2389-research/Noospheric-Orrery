# ABOUTME: Read a staged ccvault session archive (its SQLite) — the neutral capture layer.
# ABOUTME: Orrery does ALL interpretation here; ccvault is never mutated. See docs/ccvault-ingestion.md.

import json
import os
import re
import sqlite3

# The MCP tags emitted by #93 live inside tool_result content; the tool NAME is the
# detect signal for graph-work (Flow B). Kept here so reader + job agree on the prefix.
ORRERY_MCP_PREFIX = "mcp__noospheric-orrery__"

# Two capture shapes, because the graph is reached two ways:
#  - MCP output — reserved-prefix tags (the #93 contract): [entity:id], [doc:id], [query:qry_…].
#    Titles are printed bracketed, so match the prefixes, never any [...].
#  - Bare API JSON — a curl/SDK hit lands raw JSON in a Bash tool_result: entity ids as JSON
#    fields and "query_id":"qry_…" (the API now returns it). Parsed by _harvest_json below.
_TAG_RE = re.compile(r"\[(entity|doc|image):([^\]]+)\]")
# query_id is prefixed + fixed-shape, so ONE regex recovers it from either form (tag or JSON).
_QID_RE = re.compile(r"qry_[0-9a-f]{32}")


def _looks_like_entity(d: dict) -> bool:
    """An entity node across every API shape: an id plus a canonical/typed name. Excludes
    documents ({id,title}) and chunks ({chunk_id,…}), whose ids are not entity ids."""
    return isinstance(d, dict) and "id" in d and (
        "canonical_name" in d or ("name" in d and "type" in d))


def _walk_json_ids(obj, entity_ids: set, doc_ids: set):
    """Recursively collect entity ids (entity-like dicts) and doc ids (document_id, or the
    top-level id of an entity-detail's sources) from a parsed orrery-API response."""
    if isinstance(obj, dict):
        if _looks_like_entity(obj):
            entity_ids.add(obj["id"])
        if obj.get("document_id"):
            doc_ids.add(obj["document_id"])
        for v in obj.values():
            _walk_json_ids(v, entity_ids, doc_ids)
    elif isinstance(obj, list):
        for v in obj:
            _walk_json_ids(v, entity_ids, doc_ids)


def _harvest_json(text: str, entity_ids: set, doc_ids: set):
    """Best-effort: if a tool_result body is (or contains) an orrery-API JSON response, pull
    entity/doc ids from it. Handles a clean `curl -s` body directly; falls back to the largest
    balanced {...} substring when the model wrapped the JSON in other text."""
    if not text or ('"id"' not in text and '"document_id"' not in text):
        return
    for candidate in (text, _largest_json_object(text)):
        if not candidate:
            continue
        try:
            _walk_json_ids(json.loads(candidate), entity_ids, doc_ids)
            return
        except Exception:
            continue


def _largest_json_object(text: str):
    start = text.find("{")
    end = text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else None


def resolve_db_path(path: str) -> str:
    """Accept either a ccvault.db file or a directory that contains one (staged the way
    repos stage under /data/repos)."""
    if os.path.isdir(path):
        cand = os.path.join(path, "ccvault.db")
        if not os.path.exists(cand):
            raise FileNotFoundError(f"no ccvault.db under {path}")
        return cand
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return path


def open_archive(path: str) -> sqlite3.Connection:
    """Open the archive READ-ONLY — we consume ccvault's output, never write to it."""
    db = resolve_db_path(path)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_sessions(conn: sqlite3.Connection, source: str = "claude-code") -> list[dict]:
    """Sessions in the archive, oldest first. `source=''` takes all tools; the default
    limits to Claude Code (Codex has a different tool-call shape — deferred)."""
    rows = conn.execute(
        "SELECT s.id AS session_id, p.path AS project_path, s.started_at, "
        "       s.turn_count, s.source "
        "FROM sessions s LEFT JOIN projects p ON p.id = s.project_id "
        "WHERE (? = '' OR s.source = ?) "
        "ORDER BY s.started_at, s.id",
        (source, source),
    ).fetchall()
    return [dict(r) for r in rows]


def session_tool_names(conn: sqlite3.Connection, session_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT tool_name FROM tool_uses WHERE session_id = ?", (session_id,)
    ).fetchall()
    return {r[0] for r in rows if r[0]}


def uses_orrery_graph(conn: sqlite3.Connection, session_id: str) -> bool:
    """True if the session called any orrery MCP tool — the Flow B detect gate."""
    return any(t.startswith(ORRERY_MCP_PREFIX) for t in session_tool_names(conn, session_id))


def session_transcript(conn: sqlite3.Connection, session_id: str, max_chars: int = 24000) -> str:
    """A compact, readable transcript for summarization.

    Built from the FTS `content` column (ccvault's human-readable extract). Tool blobs are
    truncated there — fine for a session-level summary, which wants the gist of the work,
    not full tool payloads (those live in raw_json, used by Flow B). Ordered chronologically
    and capped head+tail so both the setup and the outcome of a long session survive.
    """
    rows = conn.execute(
        "SELECT type, content FROM turns "
        "WHERE session_id = ? AND type IN ('user','assistant') "
        "  AND content IS NOT NULL AND content != '' "
        "ORDER BY timestamp, id",
        (session_id,),
    ).fetchall()
    parts = [f"[{r['type']}] {r['content'].strip()}" for r in rows if (r["content"] or "").strip()]
    full = "\n\n".join(parts)
    if len(full) <= max_chars:
        return full
    head = full[: max_chars * 2 // 3]
    tail = full[-(max_chars // 3):]
    return f"{head}\n\n…[{len(full) - max_chars} chars elided]…\n\n{tail}"


def _turn_message(raw_json):
    """The `message` object from a turn's raw_json (bytes or str), or None."""
    if raw_json is None:
        return None
    if isinstance(raw_json, (bytes, bytearray)):
        raw_json = raw_json.decode("utf-8", "replace")
    try:
        obj = json.loads(raw_json)
    except Exception:
        return None
    return obj.get("message") if isinstance(obj, dict) else None


def _content_blocks(msg):
    if isinstance(msg, dict) and isinstance(msg.get("content"), list):
        return [b for b in msg["content"] if isinstance(b, dict)]
    return []


def graph_work(conn, session_id, max_synthesis_chars=16000):
    """Parse a session's orrery-graph interaction from raw_json (Flow B input).

    Walks turns in order and pulls, from the FULL raw_json (never the truncated `content`):
      - query_ids  : ordered, de-duplicated `[query:…]` correlation ids
      - entity_ids / doc_ids / image_ids : the tagged ids the work touched
      - tool_calls : (short_tool_name, input) for each orrery MCP call (the questions asked)
      - synthesis  : the assistant's own text (what it concluded), capped
    Tags are read by reserved prefix only. Only orrery MCP tool calls count as graph-work.
    """
    rows = conn.execute(
        "SELECT type, content, raw_json FROM turns WHERE session_id = ? ORDER BY timestamp, id",
        (session_id,),
    ).fetchall()
    query_ids: list[str] = []
    entity_ids: set[str] = set()
    doc_ids: set[str] = set()
    image_ids: set[str] = set()
    tool_calls: list[tuple] = []
    synth: list[str] = []

    def _note_query_ids(text):
        for q in _QID_RE.findall(text or ""):
            if q not in query_ids:
                query_ids.append(q)

    for r in rows:
        blocks = _content_blocks(_turn_message(r["raw_json"]))
        if not blocks:
            if r["type"] == "assistant" and (r["content"] or "").strip():
                synth.append(r["content"].strip())
            continue
        for b in blocks:
            t = b.get("type")
            if t == "tool_use" and str(b.get("name", "")).startswith(ORRERY_MCP_PREFIX):
                tool_calls.append((b["name"].split("__")[-1], b.get("input")))
            elif t == "tool_use" and b.get("name") == "Bash":
                cmd = (b.get("input") or {}).get("command", "") if isinstance(b.get("input"), dict) else ""
                # A bare API call to the graph (curl/httpie/wget to a read endpoint) is graph-work too.
                if any(p in cmd for p in ("/search", "/entities", "/graph/", "/documents", "/domains")) \
                        and any(c in cmd for c in ("curl", "http", "wget", "fetch")):
                    tool_calls.append(("bash-api", cmd[:200]))
            elif t == "text" and r["type"] == "assistant" and (b.get("text") or "").strip():
                synth.append(b["text"].strip())
            elif t == "tool_result":
                c = b.get("content")
                txt = c if isinstance(c, str) else "".join(
                    x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else ""
                txt = txt or ""
                # MCP tags (entity/doc/image) + query_ids in either form ([query:…] or "query_id":…)
                for kind, val in _TAG_RE.findall(txt):
                    (entity_ids if kind == "entity" else doc_ids if kind == "doc" else image_ids).add(val)
                _note_query_ids(txt)
                # Bare API JSON: harvest entity/doc ids straight from the response body.
                _harvest_json(txt, entity_ids, doc_ids)
    synthesis = "\n\n".join(synth)
    if len(synthesis) > max_synthesis_chars:
        synthesis = synthesis[:max_synthesis_chars] + f"\n…[{len(synthesis) - max_synthesis_chars} chars elided]…"
    return {"query_ids": query_ids, "entity_ids": entity_ids, "doc_ids": doc_ids,
            "image_ids": image_ids, "tool_calls": tool_calls, "synthesis": synthesis}


def _event_of_turn(r):
    """One transcript event from a turn: its readable text, plus any graph ids harvested from
    its tool_result content (tags AND bare-API JSON). Ids are pulled BEFORE the text is
    truncated for display, so nothing is lost to the cap."""
    text_parts, qids, eids, dids = [], [], set(), set()
    blocks = _content_blocks(_turn_message(r["raw_json"]))
    if not blocks:
        if r["type"] in ("user", "assistant") and (r["content"] or "").strip():
            text_parts.append(f"[{r['type']}] {r['content'].strip()}")
        return {"text": "\n".join(text_parts), "query_ids": qids, "entity_ids": eids, "doc_ids": dids}
    for b in blocks:
        t = b.get("type")
        if t == "text" and (b.get("text") or "").strip():
            text_parts.append(f"[{r['type']}] {b['text'].strip()}")
        elif t == "tool_use":
            nm = (b.get("name") or "").split("__")[-1]
            inp = b.get("input")
            text_parts.append(f"[tool:{nm}] {json.dumps(inp)[:300] if inp is not None else ''}")
        elif t == "tool_result":
            c = b.get("content")
            txt = c if isinstance(c, str) else "".join(
                x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else ""
            txt = txt or ""
            for kind, val in _TAG_RE.findall(txt):
                (eids if kind == "entity" else dids).add(val)
            for q in _QID_RE.findall(txt):
                if q not in qids:
                    qids.append(q)
            _harvest_json(txt, eids, dids)
            text_parts.append(f"[result] {txt[:400]}")
    return {"text": "\n".join(text_parts), "query_ids": qids, "entity_ids": eids, "doc_ids": dids}


def iter_segments(conn, session_id, target_chars=3000, max_segments=8):
    """Partition a session into ordered SEGMENTS — the leaves of the session's recursive
    summary (docs/ccvault-ingestion.md). A segment is a contiguous run of turns of roughly
    `target_chars`, so the model summarizes coherent units of work rather than one giant blob.
    Each segment carries the graph ids (query_ids/entity_ids/doc_ids) harvested from its own
    tool results, so a graph-using segment can become an entity-anchored active-work leaf while
    its neighbours become neutral leaves. Capped at `max_segments` (tail merged) to bound cost.
    """
    rows = conn.execute(
        "SELECT type, content, raw_json FROM turns WHERE session_id = ? ORDER BY timestamp, id",
        (session_id,),
    ).fetchall()

    def _fresh():
        return {"text": [], "query_ids": [], "entity_ids": set(), "doc_ids": set(), "size": 0}

    def _finalize(seg):
        return {"text": "\n\n".join(t for t in seg["text"] if t.strip()),
                "query_ids": seg["query_ids"],
                "entity_ids": seg["entity_ids"], "doc_ids": seg["doc_ids"],
                "is_graph_work": bool(seg["query_ids"] or seg["entity_ids"])}

    segments, cur = [], _fresh()
    for r in rows:
        ev = _event_of_turn(r)
        if not ev["text"] and not ev["query_ids"] and not ev["entity_ids"]:
            continue
        cur["text"].append(ev["text"])
        cur["size"] += len(ev["text"])
        for q in ev["query_ids"]:
            if q not in cur["query_ids"]:
                cur["query_ids"].append(q)
        cur["entity_ids"] |= ev["entity_ids"]
        cur["doc_ids"] |= ev["doc_ids"]
        if cur["size"] >= target_chars:
            segments.append(cur)
            cur = _fresh()
    if cur["size"] > 0:
        segments.append(cur)

    # Cap segment count by merging the smallest-adjacent pairs from the end (keeps order).
    while len(segments) > max_segments:
        a = segments.pop()
        b = segments[-1]
        b["text"] += a["text"]
        b["size"] += a["size"]
        for q in a["query_ids"]:
            if q not in b["query_ids"]:
                b["query_ids"].append(q)
        b["entity_ids"] |= a["entity_ids"]
        b["doc_ids"] |= a["doc_ids"]
    return [_finalize(s) for s in segments]
