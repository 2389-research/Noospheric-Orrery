import sqlite3
import uuid
import pytest
from src.db import init_db
from src.jobs.graph_repair import judge_pending_issues, judge_correction


class FakeRelay:
    """Duck-typed stand-in for orrery_relay.Relay. Records prompts, returns a canned verdict."""
    def __init__(self, verdict="reject", confidence=0.9, rationale="stub"):
        self._v = {"verdict": verdict, "confidence": confidence, "rationale": rationale}
        self.calls = []

    async def complete_structured(self, *, model, messages, max_tokens, schema, **kwargs):
        self.calls.append(messages[0]["content"])
        return dict(self._v)


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
