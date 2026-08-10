"""make_summarize_fn must dispatch per level, call the relay's SYNC method with
a system prompt, and return the stripped .text."""
from orrery_codesum import make_summarize_fn


class FakeResp:
    def __init__(self, text="  a summary  "):
        self.text = text


class FakeRelay:
    def __init__(self):
        self.calls = []

    def complete_sync(self, model, messages, max_tokens, system=None, temperature=None):
        self.calls.append({
            "model": model, "messages": messages, "max_tokens": max_tokens,
            "system": system, "temperature": temperature,
        })
        return FakeResp()

    def complete(self, *a, **k):  # async in real relay — must NOT be used here
        raise AssertionError("summarize_fn must use complete_sync, not complete")


def test_summarize_fn_uses_complete_sync_and_strips():
    relay = FakeRelay()
    fn = make_summarize_fn(relay, "claude-haiku-4-5")
    out = fn("leaf", path="mod/a.py", content="import os", root="repo ctx")
    assert out == "a summary"                       # stripped
    assert len(relay.calls) == 1
    call = relay.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["system"] is not None              # every level carries a system prompt
    assert "FILE CONTENT" in call["messages"][0]["content"]
    assert "repo ctx" in call["messages"][0]["content"]


def test_each_level_has_a_distinct_prompt_and_budget():
    relay = FakeRelay()
    fn = make_summarize_fn(relay, "m")
    fn("root_provisional", path=".", content="deps + tree")
    fn("module", path="mod", root="r", parent="p", files="f1\nf2", submods="sub")
    fn("root_final", path=".", parent="prov", files="module summaries")
    systems = [c["system"] for c in relay.calls]
    assert len(set(systems)) == 3                  # distinct system prompt per level
    budgets = [c["max_tokens"] for c in relay.calls]
    assert budgets == [400, 350, 450]              # root_provisional / module / root_final


def test_unknown_level_raises():
    fn = make_summarize_fn(FakeRelay(), "m")
    try:
        fn("bogus", path="x")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown level")
