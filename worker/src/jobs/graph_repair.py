# ABOUTME: Advisory correction judge — worker job. Reads pending graph_issues, judges each
# with a bounded non-agentic relay call, writes advisory {verdict, confidence, rationale}.
# Ported from the validated DS-scratch probe. NEVER mutates the graph, NEVER gates.
import sqlite3

MAX_NEIGHBORS = 15

ACTION_FRAMING = {
    "invalidate": "Decide: is this node NOT a real entity of its kind (a metaphor, analogy, or extraction artifact)? Default skeptical: only ACCEPT if the source text shows it is not a genuine referent.",
    "merge": "Decide: do these two nodes denote the SAME real-world referent? Reject firm-vs-founder, product-vs-company, and distinct-but-similar names. Only ACCEPT if the sources show one referent.",
    "retype": "Decide: does the source usage show the CURRENT type is wrong AND the proposed type is right? Only ACCEPT if both hold.",
    "rename": "Decide: is the current name a garbled/misspelled form of a real referent, and is the proposed name the correct form? Only ACCEPT if the correction is clearly right.",
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["accept", "reject", "defer"],
                    "description": "accept = correction justified; reject = correction wrong; defer = unsure / needs human or different action."},
        "confidence": {"type": "number", "description": "0.0-1.0 confidence in the verdict."},
        "rationale": {"type": "string", "description": "1-3 sentences grounded in the evidence pack."},
    },
    "required": ["verdict", "confidence", "rationale"],
}


def _entity_evidence(conn: sqlite3.Connection, entity_id: str, name: str) -> dict:
    """Type + FULL source chunks + neighborhood for ONE specific entity id (the probe lesson:
    FULL chunks). Scoped by id, not name, so different-type homonyms are never mixed together."""
    types = [r[0] for r in conn.execute(
        "SELECT DISTINCT type FROM entities WHERE id = ?", (entity_id,)).fetchall()]
    if not types:
        return {"name": name, "found": False}
    chunks = [r[0] for r in conn.execute(
        "SELECT DISTINCT c.text FROM entity_sources es JOIN chunks c ON c.id = es.chunk_id "
        "WHERE es.entity_id = ?", (entity_id,)).fetchall() if r[0]]
    nbrs = conn.execute(
        "SELECT e.canonical_name, r.weight FROM relationships r JOIN entities e "
        "ON e.id = CASE WHEN r.from_entity = ? THEN r.to_entity ELSE r.from_entity END "
        "WHERE r.from_entity = ? OR r.to_entity = ? ORDER BY r.weight DESC LIMIT ?",
        (entity_id, entity_id, entity_id, MAX_NEIGHBORS)).fetchall()
    return {"name": name, "found": True, "id": entity_id, "types": types, "chunks": chunks,
            "neighbors": [f"{n} (w={int(w) if w else w})" for n, w in nbrs]}


def _build_prompt(issue: dict, evidence: list[dict]) -> str:
    parts = [
        "You are an adversarial reviewer of a proposed correction to a knowledge graph.",
        "Your default stance is SKEPTICAL: try to REFUTE the proposal. Judge ONLY from the",
        "evidence pack below plus widely-known facts. Do NOT assume the proposal is correct.",
        "", f"ACTION: {issue['action']}", ACTION_FRAMING.get(issue["action"], ""),
        "", f"PROPOSAL: {issue.get('rationale') or '(no rationale given)'}",
    ]
    if issue.get("proposed_type"):
        parts.append(f"PROPOSED NEW TYPE: {issue['proposed_type']}")
    if issue.get("proposed_name"):
        parts.append(f"PROPOSED NEW NAME: {issue['proposed_name']}")
    parts += ["", "=== EVIDENCE PACK ==="]
    for ev in evidence:
        parts.append(f"\n## Entity: {ev['name']}")
        if not ev.get("found"):
            parts.append("(NOT FOUND IN GRAPH)")
            continue
        parts.append(f"Current type(s): {', '.join(ev['types']) or '(none)'}")
        parts.append(f"Neighbors (by co-occurrence weight): {', '.join(ev['neighbors']) or '(none)'}")
        parts.append(f"Source chunks ({len(ev['chunks'])}):")
        for i, ch in enumerate(ev["chunks"], 1):
            parts.append(f"[chunk {i}] {ch.strip()}")
    parts += ["", "ACCEPT only if the evidence clearly justifies the correction; REJECT if the "
              "entity/relationship is correct as-is; DEFER if genuinely unsure or a different action "
              "fits better. Respond directly; do not use extended thinking."]
    return "\n".join(parts)


VALID_VERDICTS = {"accept", "reject", "defer"}


async def judge_correction(conn: sqlite3.Connection, relay, issue: dict, model: str) -> dict:
    """One bounded, action-aware, source-grounded verdict for a single issue. Injected relay
    (duck-typed complete_structured) + model string — no live-model dependency in the caller's tests.
    Evidence is gathered by the row's resolved entity id(s), never by name, so different-type
    homonyms are never conflated."""
    targets = [(issue["target_entity_id"], issue["target_entity_name"])]
    if issue["action"] == "merge" and issue.get("target_b_entity_id"):
        targets.append((issue["target_b_entity_id"],
                        issue.get("target_b_name") or issue["target_b_entity_id"]))
    evidence = [_entity_evidence(conn, eid, name) for eid, name in targets]
    result = await relay.complete_structured(
        model=model, messages=[{"role": "user", "content": _build_prompt(issue, evidence)}],
        max_tokens=1024, schema=VERDICT_SCHEMA, tool_name="verdict",
        tool_description="Return the adversarial review verdict for this proposed correction.",
        temperature=0.0,
    )
    return {"verdict": (result.get("verdict") or "").lower(),
            "confidence": result.get("confidence"),
            "rationale": result.get("rationale", "")}


async def judge_pending_issues(conn: sqlite3.Connection, relay, model: str) -> dict:
    """Judge every pending, un-judged issue; write advisory columns. Idempotent (skips already-judged).

    Per-issue isolation: each issue is judged + committed independently, so one relay failure never
    rolls back others (no batch poison pill) and partial progress survives. A blank/invalid verdict
    (empty, out-of-enum, or missing confidence) is treated as a FAILURE and left NULL so a re-run
    retries it — never latched as a non-NULL empty string. Uses a local cursor so it never mutates
    the caller's connection row_factory (matches the intake pipeline convention)."""
    cursor = conn.execute(
        "SELECT * FROM graph_issues WHERE status = 'pending' AND judge_verdict IS NULL "
        "ORDER BY created_at ASC")
    columns = [c[0] for c in cursor.description]
    issues = [dict(zip(columns, row)) for row in cursor.fetchall()]
    judged = 0
    failed = 0
    for issue in issues:
        try:
            v = await judge_correction(conn, relay, issue, model)
            verdict, confidence = v["verdict"], v["confidence"]
            if verdict not in VALID_VERDICTS or confidence is None:
                # Blank/garbage verdict (no tool_use, parse fail, etc.) — leave NULL, retry next run.
                failed += 1
                print(f"judge_corrections: issue {issue['id']} invalid verdict "
                      f"{verdict!r}/conf={confidence!r} — left un-judged", flush=True)
                continue
            conn.execute(
                "UPDATE graph_issues SET judge_verdict = ?, judge_confidence = ?, judge_rationale = ? WHERE id = ?",
                (verdict, confidence, v["rationale"], issue["id"]))
            conn.commit()
            judged += 1
        except Exception as e:
            failed += 1
            print(f"judge_corrections: issue {issue['id']} failed: {e}", flush=True)
            continue
    return {"judged": judged, "failed": failed}


async def run_judge_corrections(job: dict, db_path: str) -> None:
    """Worker entrypoint: judge all pending issues in this workspace DB. Lazy Relay import
    (mirrors handle_job's lazy handler imports) so the pure functions stay import-light."""
    from orrery_relay import Relay
    from ..config import get_settings
    from ..db import get_connection
    settings = get_settings()
    relay = Relay.from_settings(settings)
    conn = get_connection(db_path)
    try:
        result = await judge_pending_issues(conn, relay, settings.classification_model)
        print(f"judge_corrections: judged {result['judged']} pending issue(s), "
              f"{result['failed']} failed/left un-judged", flush=True)
    finally:
        conn.close()
