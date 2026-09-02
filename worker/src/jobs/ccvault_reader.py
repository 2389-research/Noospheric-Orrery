# ABOUTME: Read a staged ccvault session archive (its SQLite) — the neutral capture layer.
# ABOUTME: Orrery does ALL interpretation here; ccvault is never mutated. See docs/ccvault-ingestion.md.

import json
import os
import re
import sqlite3

# The MCP tags emitted by #93 live inside tool_result content; the tool NAME is the
# detect signal for graph-work (Flow B). Kept here so reader + job agree on the prefix.
ORRERY_MCP_PREFIX = "mcp__noospheric-orrery__"

# Recovery is by RESERVED PREFIX only (the #93 contract): document titles are printed
# bracketed and are free-form, so match these prefixes, never any [...].
_TAG_RE = re.compile(r"\[(query|entity|doc|image):([^\]]+)\]")


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
            elif t == "text" and r["type"] == "assistant" and (b.get("text") or "").strip():
                synth.append(b["text"].strip())
            elif t == "tool_result":
                c = b.get("content")
                txt = c if isinstance(c, str) else "".join(
                    x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else ""
                for kind, val in _TAG_RE.findall(txt or ""):
                    if kind == "query":
                        if val not in query_ids:
                            query_ids.append(val)
                    elif kind == "entity":
                        entity_ids.add(val)
                    elif kind == "doc":
                        doc_ids.add(val)
                    elif kind == "image":
                        image_ids.add(val)
    synthesis = "\n\n".join(synth)
    if len(synthesis) > max_synthesis_chars:
        synthesis = synthesis[:max_synthesis_chars] + f"\n…[{len(synthesis) - max_synthesis_chars} chars elided]…"
    return {"query_ids": query_ids, "entity_ids": entity_ids, "doc_ids": doc_ids,
            "image_ids": image_ids, "tool_calls": tool_calls, "synthesis": synthesis}
