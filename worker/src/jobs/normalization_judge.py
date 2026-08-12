# ABOUTME: Advisory normalization judge — drains the 0.76-0.84 review backlog an
# ABOUTME: LLM at a time. Batched, source-grounded merge/keep verdicts; idle-only.

"""Normalization review-queue judge.

The embedding normalizer auto-merges pairs at >=0.85 and queues the 0.76-0.84
band for review — cross-repo equivalents worded differently. That queue grows
without bound (15k+ on the 5-repo run) and threshold-tuning can't fix it: the
band is ~85% should-KEEP with embedding traps (`top_k`/`top_p`,
`readfile`/`writefile`) an auto-merge would wrongly fuse.

An eval (issue #6) showed a conservative LLM judge — Haiku *and* local
`gemma4:26b` both 7/8 vs a hand reference — reliably separates real merges from
those traps when grounded with each entity's type + a source excerpt. This is
that judge, run as a **low-priority, idle-only** sweep (see `poll_loop`): it
sips spare worker cycles in bounded batches and yields immediately to real jobs.

Modes: `off` | `advise` (write verdicts only) | `apply` (also auto-resolve
confident KEEPs — safe: keeping two nodes separate never mutates the graph).
Confident MERGEs are written as advisory verdicts and left for the human-gated /
corrections path; this job never runs the naive `_merge_entities` (which
double-counts edges + hard-deletes). Advisory-only, exactly like the
corrections judge.
"""

import json
import math
import time
import urllib.request

MODES = ("off", "advise", "apply")
VALID_VERDICTS = {"merge", "keep", "unsure"}
_EXCERPT_CHARS = 300

# Model selection: prefer a local Ollama model, fall back to the cloud model.
# The probe result (and the built Ollama relay) is cached for this TTL so we
# don't hit /api/tags — or eat a 2s timeout when Ollama is down — every sweep.
_LOCAL_PROBE_TTL = 60.0
_judge_target: dict = {"decided_at": None, "source": None, "relay": None}


def probe_ollama_model(ollama_url: str, model: str, timeout: float = 2.0) -> bool:
    """True if Ollama is reachable at ollama_url and serves `model` (tag or base
    name). Any error (down, timeout, bad JSON) → False (fall back to cloud)."""
    try:
        with urllib.request.urlopen(ollama_url.rstrip("/") + "/api/tags", timeout=timeout) as resp:
            names = {m.get("name", "") for m in json.loads(resp.read().decode()).get("models", [])}
    except Exception:
        return False
    base = model.split(":")[0]
    return any(n == model or n == base or n.split(":")[0] == base for n in names)


def reset_judge_target() -> None:
    """Test/hot-reload helper: drop the cached model-selection decision."""
    _judge_target.update(decided_at=None, source=None, relay=None)


def resolve_judge_relay(settings, primary_relay, *, now: float | None = None, probe=probe_ollama_model):
    """Pick (relay, model, source) for the judge: local Ollama if reachable with
    the configured model, else the cloud fallback (`normalization_judge_model` or
    `extraction_model`) on the primary relay. Cached for `_LOCAL_PROBE_TTL`."""
    now = time.monotonic() if now is None else now
    fallback_model = settings.normalization_judge_model or settings.extraction_model
    fallback = (primary_relay, fallback_model, settings.anthropic_backend)

    if not settings.normalization_judge_prefer_local or not settings.normalization_judge_local_model:
        return fallback

    local_model = settings.normalization_judge_local_model
    decided_at = _judge_target["decided_at"]
    if decided_at is not None and (now - decided_at) < _LOCAL_PROBE_TTL:
        if _judge_target["source"] == "ollama":
            return _judge_target["relay"], local_model, "ollama"
        return fallback

    if probe(settings.ollama_url, local_model):
        relay = _judge_target["relay"]
        if relay is None:
            from orrery_relay import Relay
            relay = Relay.from_settings(settings, backend="ollama")
        _judge_target.update(decided_at=now, source="ollama", relay=relay)
        return relay, local_model, "ollama"

    _judge_target.update(decided_at=now, source="fallback", relay=None)
    return fallback

VERDICTS_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "the PAIR number from the prompt"},
                    "verdict": {"type": "string", "enum": ["merge", "keep", "unsure"],
                                "description": "merge = same real referent; keep = distinct; unsure = genuinely borderline."},
                    "confidence": {"type": "number", "description": "0.0-1.0"},
                    "rationale": {"type": "string", "description": "one short sentence."},
                },
                "required": ["index", "verdict", "confidence"],
            },
        }
    },
    "required": ["verdicts"],
}


def _usable_confidence(value) -> bool:
    """True only for a finite number in [0, 1].

    `value is not None` was the whole check, so a model returning a string or a list
    reached the SQLite binding (which raises and kills the entire chunk, not just the
    pair) and the `>= min_confidence` comparison (which raises on a str under Python 3).
    A number above 1.0 also passed, and in `apply` mode that auto-resolves a keep on
    a confidence the model was never entitled to claim.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and 0.0 <= value <= 1.0


def _evidence(conn, entity_id: str) -> tuple[str, str]:
    """This entity's type + one short source excerpt — the grounding the eval
    found necessary to separate genuine merges from same-name/different-thing."""
    row = conn.execute(
        "SELECT type FROM entities WHERE id = ? AND invalid_at IS NULL", (entity_id,)
    ).fetchone()
    etype = (row[0] if row else None) or "?"
    ex = conn.execute(
        "SELECT c.text FROM entity_sources es JOIN chunks c ON c.id = es.chunk_id "
        "WHERE es.entity_id = ? AND c.text IS NOT NULL AND c.text != '' LIMIT 1",
        (entity_id,),
    ).fetchone()
    excerpt = (ex[0][:_EXCERPT_CHARS].strip() if ex and ex[0] else "")
    return etype, excerpt


def _build_prompt(items: list[dict]) -> str:
    """items: [{index, a_name, a_type, a_excerpt, b_name, b_type, b_excerpt, sim}]."""
    parts = [
        "Deduplicate a knowledge graph. For each candidate PAIR, decide `merge` if A and B",
        "name the SAME thing, or `keep` if they are DIFFERENT. Every pair is already",
        "embedding-similar, so most are NEAR-MISSES meant to catch over-merging. When",
        "genuinely unsure, `keep`.",
        "",
        "`merge` ONLY when the difference is purely surface — the SAME core concept:",
        "  - spelling / spacing / punctuation / casing:  \"trace event\" = \"traceevent\";  \"analyze_spec\" = \"analyzespec\"",
        "  - word order:  \"dippin ai pipeline workflows\" = \"dippin workflow pipeline\"",
        "  - a GENERIC FILLER noun that adds no meaning (package / function / module / service / dsl / component / tool):",
        "      \"doctor\" = \"doctor package\";  \"validatesource\" = \"validatesource function\";  \"nodelist\" = \"nodelist component\"",
        "  - a synonym for the same mechanism:  \"human-in-the-loop\" = \"human gate\"",
        "",
        "`keep` when the extra or changed word CHANGES the meaning:",
        "  - a qualifier that NARROWS scope:  \"cost tracking\" != \"per-node cost tracking\";",
        "      \"semantic validation\" != \"semantic constraint validation\";  \"spec gap\" != \"implementation gap\"",
        "  - a VERSION:  \"workflow language\" != \"workflow language v1.5\"",
        "  - a specific INSTANCE / id / route:  \"diagnostic codes\" != \"dip153 diagnostic\";  \"/x\" != \"/web/specs/{id}/x\"",
        "  - a different OPERATION / action:  \"config discovery\" != \"config loading\";  \"analysis\" != \"tracking\";",
        "      \"parser\" != \"parsing and validation\";  \"expansion\" != \"path-prefixing\"",
        "  - a different COMPONENT of the same system:  \"lsp editor integration\" != \"lsp server integration\"",
        "  - complementary opposites:  encode != decode;  readfile != writefile;  top_k != top_p",
        "",
        "KEY DISTINCTION: an extra word that is a GENERIC FILLER (package, function, module, dsl) -> still `merge`.",
        "An extra word that NARROWS scope, names a VERSION or specific INSTANCE, or a different",
        "OPERATION or COMPONENT -> `keep`.",
        "",
        "Judge from the entity TYPE and source excerpt, not the names alone. Do not use extended thinking.",
        "",
        "=== PAIRS ===",
    ]
    for it in items:
        parts.append(f"\n[pair {it['index']}] (embedding similarity {it['sim']:.2f})")
        parts.append(f"  A: \"{it['a_name']}\" (type: {it['a_type']})")
        if it["a_excerpt"]:
            parts.append(f"     source: {it['a_excerpt']}")
        parts.append(f"  B: \"{it['b_name']}\" (type: {it['b_type']})")
        if it["b_excerpt"]:
            parts.append(f"     source: {it['b_excerpt']}")
    n = len(items)
    parts += [
        "",
        "=== OUTPUT ===",
        f"Return ONLY a JSON array with exactly {n} objects, one per pair (index 0..{n - 1}),",
        "no prose, no markdown fences. Each object is exactly:",
        '  {"index": <int>, "verdict": "merge"|"keep"|"unsure", "confidence": <0..1>, "rationale": "<short>"}',
        "Example for two pairs:",
        '[{"index": 0, "verdict": "keep", "confidence": 0.9, "rationale": "complementary opposites"},'
        ' {"index": 1, "verdict": "merge", "confidence": 0.85, "rationale": "same referent, reworded"}]',
    ]
    return "\n".join(parts)


# Temperature schedule across retries. Not 0.0: greedy decoding makes a bad
# generation deterministic (it repeats identically every sweep), and Gemma-family
# models are tuned to run hotter. A moderate first pass, hotter on retry.
_RETRY_TEMPS = (0.3, 0.6, 0.9)


async def judge_batch(conn, relay, pairs: list[dict], model: str, *,
                      temperature: float = 0.3, attempts: int = 2) -> dict:
    """Bounded, schema-enforced relay call(s) over a batch. Returns
    {pair_index: {verdict, confidence, rationale}} for every returned verdict.

    complete_structured enforces the schema on both backends — Ollama's native
    `format` (grammar-constrained decoding) and cloud tool_use — so a single bad
    token can no longer nuke the whole batch. Retry (hotter each time) covers a
    rare empty response; anything still missing stays un-judged and is retried /
    counted against its attempt cap on the next sweep."""
    items = []
    for i, p in enumerate(pairs):
        a_type, a_ex = _evidence(conn, p["entity_a_id"])
        b_type, b_ex = _evidence(conn, p["entity_b_id"])
        items.append({"index": i, "a_name": p["entity_a_name"], "a_type": a_type,
                      "a_excerpt": a_ex, "b_name": p["entity_b_name"], "b_type": b_type,
                      "b_excerpt": b_ex, "sim": p["similarity"] or 0.0})
    prompt = _build_prompt(items)

    out: dict[int, dict] = {}
    for attempt in range(max(1, attempts)):
        temp = temperature if attempt == 0 else _RETRY_TEMPS[min(attempt, len(_RETRY_TEMPS) - 1)]
        try:
            result = await relay.complete_structured(
                model=model, messages=[{"role": "user", "content": prompt}],
                max_tokens=2048, schema=VERDICTS_SCHEMA, tool_name="verdicts",
                tool_description="Return one merge/keep/unsure verdict per candidate pair.",
                temperature=temp,
            )
        except Exception as e:
            print(f"norm_judge: batch relay attempt {attempt + 1}/{attempts} failed: {e}", flush=True)
            continue
        for v in (result.get("verdicts") or []):
            idx = v.get("index")
            if isinstance(idx, str) and idx.strip().lstrip("-").isdigit():
                idx = int(idx)
            if isinstance(idx, int) and 0 <= idx < len(pairs) and idx not in out:
                out[idx] = {"verdict": (v.get("verdict") or "").lower(),
                            "confidence": v.get("confidence"),
                            "rationale": v.get("rationale", "")}
        if len(out) >= len(pairs):
            break
    return out


async def run_normalization_judge_chunk(
    conn, relay, model: str, *, batch_size: int, mode: str, min_confidence: float,
    temperature: float = 0.3, max_attempts: int = 3
) -> dict:
    """Judge ONE batch of the highest-similarity un-judged pending pairs.

    Writes advisory verdict columns for every returned verdict. In `apply` mode,
    additionally resolves confident KEEPs (status='resolved') — the safe bulk of
    the backlog. Confident MERGEs are advised only (never applied here).

    Progress guarantee: a pair that fails to get a verdict has `judge_attempts`
    incremented and is excluded from the pull once it hits `max_attempts`, so a
    persistently-unparseable pair can never wedge the queue in an infinite loop.
    """
    cur = conn.execute(
        "SELECT id, entity_a_id, entity_a_name, entity_b_id, entity_b_name, similarity "
        "FROM normalization_review_queue "
        "WHERE status = 'pending' AND judge_verdict IS NULL "
        "  AND COALESCE(judge_attempts, 0) < ? "
        "ORDER BY similarity DESC LIMIT ?",
        (max_attempts, batch_size),
    )
    cols = [c[0] for c in cur.description]
    pairs = [dict(zip(cols, r)) for r in cur.fetchall()]
    stats = {"pairs": len(pairs), "judged": 0, "kept_resolved": 0,
             "merge_advised": 0, "unsure": 0, "failed": 0}
    if not pairs:
        return stats

    try:
        verdicts = await judge_batch(conn, relay, pairs, model, temperature=temperature)
    except Exception as e:
        print(f"norm_judge: batch relay call failed: {e}", flush=True)
        verdicts = {}

    # EVERY update below is guarded on `status = 'pending'`. The relay call above takes
    # seconds to minutes, and a human (or another worker) can resolve a pair in that
    # window — the SELECT that produced `pairs` is long stale by now. Updating by `id`
    # alone would let the judge overwrite a HUMAN decision with `resolution = 'kept'`,
    # which is the opposite of the human-gated property this job is built around.
    for i, p in enumerate(pairs):
        v = verdicts.get(i)
        if not v or v["verdict"] not in VALID_VERDICTS or not _usable_confidence(v.get("confidence")):
            # No usable verdict — count an attempt; after max_attempts this pair
            # drops out of the pull and stops blocking fresh pairs behind it.
            conn.execute(
                "UPDATE normalization_review_queue SET judge_attempts = "
                "COALESCE(judge_attempts, 0) + 1 WHERE id = ? AND status = 'pending'",
                (p["id"],),
            )
            stats["failed"] += 1
            continue
        cur = conn.execute(
            "UPDATE normalization_review_queue SET judge_verdict = ?, judge_confidence = ?, "
            "judge_rationale = ? WHERE id = ? AND status = 'pending'",
            (v["verdict"], v["confidence"], v["rationale"], p["id"]),
        )
        if not cur.rowcount:
            # Resolved while we were thinking. Someone else's decision stands; ours is
            # simply late, and recording it would imply the judge had a say.
            stats["skipped_resolved"] = stats.get("skipped_resolved", 0) + 1
            continue
        stats["judged"] += 1
        confident = v["confidence"] >= min_confidence
        if v["verdict"] == "keep":
            if mode == "apply" and confident:
                cur = conn.execute(
                    "UPDATE normalization_review_queue SET status = 'resolved', "
                    "resolution = 'kept' WHERE id = ? AND status = 'pending'",
                    (p["id"],),
                )
                if cur.rowcount:
                    stats["kept_resolved"] += 1
        elif v["verdict"] == "merge":
            if confident:
                stats["merge_advised"] += 1
        else:
            stats["unsure"] += 1
    conn.commit()
    return stats


async def run_normalization_judge_sweep(
    db_paths: list[str], relay, model: str, *, batch_size: int, mode: str,
    min_confidence: float, temperature: float = 0.3, max_attempts: int = 3
) -> dict:
    """One bounded chunk of work: judge a single batch in the FIRST workspace
    that still has un-judged pending pairs. Bounding to one batch per sweep is
    what keeps this yielding to real jobs (the poll loop re-checks for jobs
    before the next sweep). Per-path isolation — a bad DB is skipped."""
    from ..db import get_connection
    for db_path in db_paths:
        try:
            conn = get_connection(db_path)
            try:
                r = await run_normalization_judge_chunk(
                    conn, relay, model,
                    batch_size=batch_size, mode=mode, min_confidence=min_confidence,
                    temperature=temperature, max_attempts=max_attempts,
                )
            finally:
                conn.close()
        except Exception as e:
            print(f"norm_judge: workspace {db_path} failed: {e}", flush=True)
            continue
        if r["pairs"] > 0:
            r["workspace"] = db_path
            return r
    return {"pairs": 0, "judged": 0, "kept_resolved": 0, "merge_advised": 0,
            "unsure": 0, "failed": 0}
