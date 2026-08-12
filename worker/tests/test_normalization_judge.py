# ABOUTME: Tests for the idle-only normalization judge — advisory verdicts,
# ABOUTME: apply-mode keep resolution, malformed-verdict handling, batch grounding.

import uuid
from types import SimpleNamespace

import pytest
from src.db import init_db, get_connection
from src.jobs import normalization_judge as nj
from src.jobs.normalization_judge import (
    run_normalization_judge_chunk,
    run_normalization_judge_sweep,
    judge_batch,
    resolve_judge_relay,
    reset_judge_target,
    probe_ollama_model,
    _build_prompt,
)


def _settings(**over):
    base = dict(normalization_judge_prefer_local=True, normalization_judge_local_model="gemma4:26b",
                normalization_judge_model="", extraction_model="claude-haiku-4-5",
                ollama_url="http://ollama:11434", anthropic_backend="bedrock")
    base.update(over)
    return SimpleNamespace(**base)


class FakeRelay:
    """Returns a preset verdicts payload; records the prompt it was given."""
    def __init__(self, verdicts):
        self._verdicts = verdicts
        self.last_prompt = None

    async def complete_structured(self, *, model, messages, **kw):
        self.last_prompt = messages[0]["content"]
        return {"verdicts": self._verdicts}


def _entity(conn, eid, name, etype, chunk_text):
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, ?)", (eid, name, etype))
    did, cid = str(uuid.uuid4()), str(uuid.uuid4())
    conn.execute("INSERT INTO documents (id, title) VALUES (?, ?)", (did, name))
    conn.execute("INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) VALUES (?, ?, 0, 0, ?, ?)",
                 (cid, did, len(chunk_text), chunk_text))
    conn.execute("INSERT INTO entity_sources (entity_id, document_id, chunk_id) VALUES (?, ?, ?)", (eid, did, cid))


def _pair(conn, a, b, sim):
    rid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO normalization_review_queue (id, entity_a_id, entity_a_name, entity_b_id, entity_b_name, similarity) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (rid, a[0], a[1], b[0], b[1], sim))
    return rid


def _seed(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    _entity(conn, "e_topk", "top_k", "concept", "sampling keeps the top k tokens")
    _entity(conn, "e_topp", "top_p", "concept", "nucleus sampling by cumulative probability p")
    _entity(conn, "e_rs1", "recursive summarization", "capability", "summarize modules recursively")
    _entity(conn, "e_rs2", "recursive summariser", "capability", "the recursive summariser walks the tree")
    # pair 0 (sim 0.84): a trap that must KEEP; pair 1 (sim 0.80): a real MERGE
    _pair(conn, ("e_topk", "top_k"), ("e_topp", "top_p"), 0.84)
    _pair(conn, ("e_rs1", "recursive summarization"), ("e_rs2", "recursive summariser"), 0.80)
    conn.commit()
    return db_path, conn


async def test_advise_writes_verdicts_leaves_pending(tmp_path):
    db_path, conn = _seed(tmp_path)
    relay = FakeRelay([
        {"index": 0, "verdict": "keep", "confidence": 0.95, "rationale": "opposites"},
        {"index": 1, "verdict": "merge", "confidence": 0.9, "rationale": "same thing"},
    ])
    stats = await run_normalization_judge_chunk(
        conn, relay, "m", batch_size=10, mode="advise", min_confidence=0.75)

    assert stats["pairs"] == 2 and stats["judged"] == 2 and stats["failed"] == 0
    # advise never resolves anything
    assert stats["kept_resolved"] == 0
    rows = conn.execute(
        "SELECT judge_verdict, status FROM normalization_review_queue ORDER BY similarity DESC").fetchall()
    assert [r[0] for r in rows] == ["keep", "merge"]
    assert all(r[1] == "pending" for r in rows)  # nothing resolved in advise mode


async def test_apply_resolves_confident_keep_but_not_merge(tmp_path):
    db_path, conn = _seed(tmp_path)
    relay = FakeRelay([
        {"index": 0, "verdict": "keep", "confidence": 0.95, "rationale": "opposites"},
        {"index": 1, "verdict": "merge", "confidence": 0.9, "rationale": "same thing"},
    ])
    stats = await run_normalization_judge_chunk(
        conn, relay, "m", batch_size=10, mode="apply", min_confidence=0.75)

    assert stats["kept_resolved"] == 1      # the confident keep drained
    assert stats["merge_advised"] == 1      # the merge is advised, NOT auto-applied
    by_sim = conn.execute(
        "SELECT judge_verdict, status, resolution FROM normalization_review_queue ORDER BY similarity DESC").fetchall()
    assert tuple(by_sim[0]) == ("keep", "resolved", "kept")   # keep resolved
    assert tuple(by_sim[1]) == ("merge", "pending", None)     # merge left for human/corrections
    # entities are untouched — the judge never merges here
    assert conn.execute("SELECT COUNT(*) FROM entities WHERE invalid_at IS NULL").fetchone()[0] == 4


async def test_low_confidence_keep_not_resolved(tmp_path):
    db_path, conn = _seed(tmp_path)
    relay = FakeRelay([
        {"index": 0, "verdict": "keep", "confidence": 0.60, "rationale": "maybe"},
        {"index": 1, "verdict": "unsure", "confidence": 0.5, "rationale": "borderline"},
    ])
    stats = await run_normalization_judge_chunk(
        conn, relay, "m", batch_size=10, mode="apply", min_confidence=0.75)
    assert stats["kept_resolved"] == 0 and stats["unsure"] == 1
    # verdict still recorded (advisory), but stays pending
    assert conn.execute(
        "SELECT COUNT(*) FROM normalization_review_queue WHERE status='pending'").fetchone()[0] == 2


async def test_malformed_verdict_left_unjudged(tmp_path):
    db_path, conn = _seed(tmp_path)
    # pair 1 missing from the response, pair 0 has an out-of-enum verdict
    relay = FakeRelay([{"index": 0, "verdict": "banana", "confidence": 0.9, "rationale": "x"}])
    stats = await run_normalization_judge_chunk(
        conn, relay, "m", batch_size=10, mode="apply", min_confidence=0.75)
    assert stats["judged"] == 0 and stats["failed"] == 2
    # both left NULL so a re-run retries them
    assert conn.execute(
        "SELECT COUNT(*) FROM normalization_review_queue WHERE judge_verdict IS NULL").fetchone()[0] == 2


async def test_prompt_includes_type_and_source_grounding(tmp_path):
    db_path, conn = _seed(tmp_path)
    relay = FakeRelay([])  # no verdicts — we only inspect the prompt
    await run_normalization_judge_chunk(conn, relay, "m", batch_size=10, mode="advise", min_confidence=0.75)
    p = relay.last_prompt
    assert "top_k" in p and "top_p" in p
    assert "type: concept" in p            # entity type grounding
    assert "nucleus sampling" in p         # source excerpt grounding


def _pairs(conn):
    cur = conn.execute(
        "SELECT id, entity_a_id, entity_a_name, entity_b_id, entity_b_name, similarity "
        "FROM normalization_review_queue ORDER BY similarity DESC")
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


async def test_judge_batch_retries_on_flaky_empty_response(tmp_path):
    """Local models sometimes return no structured output — retry recovers it."""
    _, conn = _seed(tmp_path)
    pairs = _pairs(conn)

    class FlakyRelay:
        def __init__(self): self.calls = 0
        async def complete_structured(self, **kw):
            self.calls += 1
            if self.calls == 1:
                return {"verdicts": []}  # flaky: empty on first try
            return {"verdicts": [
                {"index": 0, "verdict": "keep", "confidence": 0.9, "rationale": "x"},
                {"index": 1, "verdict": "merge", "confidence": 0.9, "rationale": "y"}]}

    relay = FlakyRelay()
    out = await judge_batch(conn, relay, pairs, "m", attempts=2)
    assert relay.calls == 2                       # retried after the empty response
    assert set(out.keys()) == {0, 1} and out[0]["verdict"] == "keep"


async def test_judge_batch_no_retry_when_first_call_complete(tmp_path):
    _, conn = _seed(tmp_path)
    pairs = _pairs(conn)

    class OneShot:
        def __init__(self): self.calls = 0
        async def complete_structured(self, **kw):
            self.calls += 1
            return {"verdicts": [
                {"index": 0, "verdict": "keep", "confidence": 0.9, "rationale": "x"},
                {"index": 1, "verdict": "merge", "confidence": 0.9, "rationale": "y"}]}

    relay = OneShot()
    out = await judge_batch(conn, relay, pairs, "m", attempts=2)
    assert relay.calls == 1 and len(out) == 2   # complete → no wasted retry


def test_resolve_prefers_local_when_ollama_has_model():
    reset_judge_target()
    nj._judge_target["relay"] = "LOCAL_RELAY"  # sentinel: skip real Relay construction
    relay, model, source = resolve_judge_relay(
        _settings(), "PRIMARY", now=100.0, probe=lambda url, m: True)
    assert (relay, model, source) == ("LOCAL_RELAY", "gemma4:26b", "ollama")
    reset_judge_target()


def test_resolve_falls_back_to_haiku_when_ollama_down():
    reset_judge_target()
    relay, model, source = resolve_judge_relay(
        _settings(), "PRIMARY", now=100.0, probe=lambda url, m: False)
    assert (relay, model, source) == ("PRIMARY", "claude-haiku-4-5", "bedrock")
    reset_judge_target()


def test_resolve_uses_explicit_cloud_model_override():
    reset_judge_target()
    s = _settings(normalization_judge_model="claude-opus-4-8")
    relay, model, source = resolve_judge_relay(s, "PRIMARY", now=100.0, probe=lambda url, m: False)
    assert model == "claude-opus-4-8"  # explicit fallback beats extraction_model
    reset_judge_target()


def test_resolve_probe_is_cached_within_ttl():
    reset_judge_target()
    calls = []
    def probe(url, m):
        calls.append(1)
        return False
    resolve_judge_relay(_settings(), "P", now=0.0, probe=probe)     # probes
    resolve_judge_relay(_settings(), "P", now=30.0, probe=probe)    # cached (TTL 60)
    assert len(calls) == 1
    resolve_judge_relay(_settings(), "P", now=90.0, probe=probe)    # TTL expired → re-probe
    assert len(calls) == 2
    reset_judge_target()


def test_resolve_prefer_local_off_skips_probe():
    reset_judge_target()
    calls = []
    r, m, src = resolve_judge_relay(
        _settings(normalization_judge_prefer_local=False), "PRIMARY", now=0.0,
        probe=lambda url, mm: calls.append(1) or True)
    assert (r, m, src) == ("PRIMARY", "claude-haiku-4-5", "bedrock") and not calls
    reset_judge_target()


def test_probe_matches_model_name(monkeypatch):
    """Hermetic: fake /api/tags, no real Ollama. Matches exact tag and base name."""
    import json as _json

    class _Resp:
        def __init__(self, payload): self._p = payload
        def read(self): return _json.dumps(self._p).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(url, timeout=None):
        return _Resp({"models": [{"name": "gemma4:26b"}, {"name": "llama3:8b"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert probe_ollama_model("http://x", "gemma4:26b") is True
    assert probe_ollama_model("http://x", "gemma4") is True      # base-name match
    assert probe_ollama_model("http://x", "mistral") is False


def test_probe_returns_false_on_error(monkeypatch):
    """Any failure (Ollama absent, timeout, bad JSON) → False, never raises."""
    def boom(url, timeout=None):
        raise OSError("connection refused")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert probe_ollama_model("http://x", "gemma4:26b") is False


async def test_sweep_skips_empty_and_returns_first_with_pending(tmp_path):
    empty = str(tmp_path / "empty.db")
    init_db(empty)
    db_path, conn = _seed(tmp_path)
    conn.close()
    relay = FakeRelay([
        {"index": 0, "verdict": "keep", "confidence": 0.9, "rationale": "x"},
        {"index": 1, "verdict": "merge", "confidence": 0.9, "rationale": "y"},
    ])
    r = await run_normalization_judge_sweep(
        [empty, db_path], relay, "m", batch_size=10, mode="advise", min_confidence=0.75)
    assert r["pairs"] == 2 and r["workspace"] == db_path


# --- the judge must never overwrite a decision made while it was thinking ------

async def test_a_human_resolution_during_the_relay_call_wins(tmp_path, monkeypatch):
    """The SELECT is stale by the time the verdict arrives.

    A relay call takes seconds to minutes, and a human (or another worker) can resolve a
    pair in that window. Updating by `id` alone let the judge overwrite a HUMAN decision
    with `resolution = 'kept'` — the opposite of the human-gated property this job is
    built around, and invisible afterwards because the row simply looks judged.
    """
    from src.db import get_connection, init_db
    from src.jobs import normalization_judge as nj

    db = str(tmp_path / "t.db")
    init_db(db)
    conn = get_connection(db)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('a','alpha','Thing')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('b','alphas','Thing')")
    conn.execute("INSERT INTO normalization_review_queue "
                 "(id, entity_a_id, entity_a_name, entity_b_id, entity_b_name, similarity) "
                 "VALUES ('p1','a','alpha','b','alphas',0.81)")
    conn.commit()

    async def judge_and_meanwhile_a_human_resolves(conn_, relay, pairs, model, **kw):
        # Exactly the window the guard protects: the human acts BEFORE the verdict lands.
        conn_.execute("UPDATE normalization_review_queue SET status='resolved', "
                      "resolution='merged' WHERE id='p1'")
        conn_.commit()
        return {0: {"verdict": "keep", "confidence": 0.99, "rationale": "distinct"}}

    monkeypatch.setattr(nj, "judge_batch", judge_and_meanwhile_a_human_resolves)

    await nj.run_normalization_judge_chunk(
        conn, relay=object(), model="m", batch_size=10, mode="apply", min_confidence=0.75)

    row = conn.execute("SELECT status, resolution, judge_verdict FROM "
                       "normalization_review_queue WHERE id='p1'").fetchone()
    conn.close()
    assert row["status"] == "resolved" and row["resolution"] == "merged", (
        f"the judge overwrote a human resolution: {tuple(row)}")
    assert row["judge_verdict"] is None, "a late verdict was recorded as if it had a say"


@pytest.mark.parametrize("bad", ["0.9", ["0.9"], {"c": 1}, None, True, float("nan"),
                                 float("inf"), -0.1, 1.5])
def test_an_unusable_confidence_is_rejected(bad):
    """`is not None` was the whole check.

    A string or list then reached the SQLite binding (which raises and kills the entire
    chunk, not just the pair) and the `>= min_confidence` comparison. A value above 1.0
    also passed, and in `apply` mode that auto-resolves a keep on a confidence the model
    was never entitled to claim.
    """
    from src.jobs.normalization_judge import _usable_confidence

    assert not _usable_confidence(bad)


@pytest.mark.parametrize("good", [0.0, 0.5, 1.0, 0, 1])
def test_a_valid_confidence_is_accepted(good):
    from src.jobs.normalization_judge import _usable_confidence

    assert _usable_confidence(good)
