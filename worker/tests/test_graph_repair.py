import sqlite3
import uuid
import pytest
from src.db import init_db, get_connection
from src.jobs.graph_repair import judge_pending_issues, judge_correction, run_judge_sweep


class FakeRelay:
    """Duck-typed stand-in for orrery_relay.Relay. Records prompts, returns a canned verdict."""
    def __init__(self, verdict="reject", confidence=0.9, rationale="stub"):
        self._v = {"verdict": verdict, "confidence": confidence, "rationale": rationale}
        self.calls = []

    async def complete_structured(self, *, model, messages, max_tokens, schema, **kwargs):
        self.calls.append(messages[0]["content"])
        return dict(self._v)


class MalformedRelay:
    """Simulates a dropped tool_use block / Ollama JSON parse failure: returns {}."""
    def __init__(self):
        self.calls = []

    async def complete_structured(self, *, model, messages, max_tokens, schema, **kwargs):
        self.calls.append(messages[0]["content"])
        return {}


class FlakyRelay:
    """Succeeds on every call except the Nth (1-indexed), which raises — poison-pill test."""
    def __init__(self, raise_on_call=2):
        self._raise_on = raise_on_call
        self.calls = 0

    async def complete_structured(self, *, model, messages, max_tokens, schema, **kwargs):
        self.calls += 1
        if self.calls == self._raise_on:
            raise RuntimeError("relay boom")
        return {"verdict": "accept", "confidence": 0.9, "rationale": "ok"}


def _seed(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', 'panopticon', 'Product')")
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc', 'extracted')")
    conn.execute("INSERT INTO chunks (id, document_id, chunk_index, text) VALUES ('c1', 'd1', 0, 'panopticon is used here as a metaphor for surveillance')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id, chunk_id) VALUES ('e1', 'd1', 'c1')")
    conn.execute(
        "INSERT INTO graph_issues (id, action, target_entity_id, target_entity_name, rationale, proposer, status) "
        "VALUES (?, 'invalidate', 'e1', 'panopticon', 'looks like a metaphor', 'agent-x', 'pending')",
        (str(uuid.uuid4()),),
    )
    conn.commit()
    return conn


async def test_judge_writes_advisory_verdict(test_db):
    conn = _seed(test_db)
    relay = FakeRelay(verdict="accept", confidence=0.88, rationale="metaphor, not a real product")
    result = await judge_pending_issues(conn, relay, model="test-model")
    assert result["judged"] == 1
    row = conn.execute("SELECT judge_verdict, judge_confidence, judge_rationale, status FROM graph_issues").fetchone()
    assert row[0] == "accept"
    assert row[1] == 0.88
    assert "metaphor" in row[2]
    assert row[3] == "pending"  # advisory only — status unchanged


async def test_judge_evidence_pack_includes_full_chunk_text(test_db):
    conn = _seed(test_db)
    relay = FakeRelay()
    await judge_pending_issues(conn, relay, model="test-model")
    prompt = relay.calls[0]
    assert "metaphor for surveillance" in prompt  # FULL source chunk text reached the judge
    assert "invalidate" in prompt.lower()          # action-aware framing


async def test_judge_skips_already_judged(test_db):
    conn = _seed(test_db)
    conn.execute("UPDATE graph_issues SET judge_verdict='reject'")
    conn.commit()
    relay = FakeRelay()
    result = await judge_pending_issues(conn, relay, model="test-model")
    assert result["judged"] == 0
    assert relay.calls == []


async def test_judge_malformed_verdict_not_latched(test_db):
    """A blank/garbage verdict must NOT be written as an empty string (which would latch the
    issue as 'judged' and never retry). It stays NULL and is counted as failed."""
    conn = _seed(test_db)
    relay = MalformedRelay()
    result = await judge_pending_issues(conn, relay, model="test-model")
    assert result["judged"] == 0
    assert result["failed"] == 1
    row = conn.execute(
        "SELECT judge_verdict, judge_confidence, judge_rationale, status FROM graph_issues"
    ).fetchone()
    assert row[0] is None  # retryable — not latched
    assert row[1] is None
    assert row[2] is None
    assert row[3] == "pending"


async def test_judge_batch_survives_one_relay_exception(test_db):
    """One relay exception must not roll back or block the rest of the batch (no poison pill).
    Successful verdicts are committed; the failing issue stays NULL and is counted."""
    conn = _seed(test_db)
    # Add a second pending issue so the batch has 2 to judge.
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e2', 'ozymandias', 'Product')")
    conn.execute(
        "INSERT INTO graph_issues (id, action, target_entity_id, target_entity_name, rationale, proposer, status) "
        "VALUES (?, 'invalidate', 'e2', 'ozymandias', 'literary analogy', 'agent-x', 'pending')",
        (str(uuid.uuid4()),),
    )
    conn.commit()
    relay = FlakyRelay(raise_on_call=2)  # second issue judged raises
    result = await judge_pending_issues(conn, relay, model="test-model")  # must NOT propagate
    assert result["judged"] == 1
    assert result["failed"] == 1
    verdicts = [r[0] for r in conn.execute("SELECT judge_verdict FROM graph_issues").fetchall()]
    # Exactly one committed verdict survived; the failure stayed NULL (retryable).
    assert verdicts.count("accept") == 1
    assert verdicts.count(None) == 1


async def test_judge_evidence_scoped_to_target_entity_id(test_db):
    """Two same-named entities of different types with different chunks. A proposal against ONE id
    must only surface THAT id's evidence — the homonym's chunk must not leak into the prompt."""
    conn = sqlite3.connect(test_db)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('planet', 'mercury', 'Planet')")
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('metal', 'mercury', 'Element')")
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc', 'extracted')")
    conn.execute("INSERT INTO chunks (id, document_id, chunk_index, text) VALUES ('cp', 'd1', 0, 'mercury is the closest planet to the sun')")
    conn.execute("INSERT INTO chunks (id, document_id, chunk_index, text) VALUES ('cm', 'd1', 1, 'mercury is a liquid metal element at room temperature')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id, chunk_id) VALUES ('planet', 'd1', 'cp')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id, chunk_id) VALUES ('metal', 'd1', 'cm')")
    conn.execute(
        "INSERT INTO graph_issues (id, action, target_entity_id, target_entity_name, rationale, proposer, status) "
        "VALUES (?, 'invalidate', 'planet', 'mercury', 'not a real planet', 'agent-x', 'pending')",
        (str(uuid.uuid4()),),
    )
    conn.commit()
    relay = FakeRelay()
    await judge_pending_issues(conn, relay, model="test-model")
    prompt = relay.calls[0]
    assert "closest planet to the sun" in prompt          # the target id's chunk
    assert "liquid metal element" not in prompt           # homonym's chunk must NOT leak
    assert "Planet" in prompt                             # target id's type
    assert "Element" not in prompt                        # homonym's type must NOT leak


def _seed_pending(db_path, name="panopticon"):
    conn = get_connection(db_path)
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES ('e1', ?, 'Product')", (name,))
    conn.execute("INSERT INTO documents (id, title, status) VALUES ('d1', 'Doc', 'extracted')")
    conn.execute("INSERT INTO chunks (id, document_id, chunk_index, text) VALUES ('c1','d1',0,'used as a metaphor')")
    conn.execute("INSERT INTO entity_sources (entity_id, document_id, chunk_id) VALUES ('e1','d1','c1')")
    conn.execute("INSERT INTO graph_issues (id, action, target_entity_id, target_entity_name, status) "
                 "VALUES ('i1','invalidate','e1',?, 'pending')", (name,))
    conn.commit(); conn.close()


async def test_sweep_judges_across_multiple_workspaces(tmp_path):
    db_a = str(tmp_path / "a.db"); db_b = str(tmp_path / "b.db")
    for p in (db_a, db_b):
        init_db(p); _seed_pending(p)
    result = await run_judge_sweep([db_a, db_b], FakeRelay(verdict="accept", confidence=0.9), model="m")
    assert result["judged"] == 2
    for p in (db_a, db_b):
        conn = get_connection(p)
        assert conn.execute("SELECT judge_verdict FROM graph_issues WHERE id='i1'").fetchone()[0] == "accept"
        conn.close()


async def test_sweep_tolerates_bad_db_path(tmp_path):
    db_a = str(tmp_path / "a.db"); init_db(db_a); _seed_pending(db_a)
    # a nonexistent path must not raise or block the good DB
    result = await run_judge_sweep([str(tmp_path / "missing.db"), db_a], FakeRelay(), model="m")
    assert result["judged"] == 1
