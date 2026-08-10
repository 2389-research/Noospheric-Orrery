import pytest

from orrery_tracksum import DIP_CATALOG, make_summarize_fn


class FakeRelay:
    """Records every complete_sync call so prompt wiring is assertable without a model."""

    def __init__(self, text="summary text"):
        self.text, self.calls = text, []

    def complete_sync(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"text": self.text})()


def test_dip_level_sends_the_full_catalog_as_system():
    relay = FakeRelay()
    make_summarize_fn(relay, "gemma4:26b")("dip", content="workflow Demo {}")
    call = relay.calls[0]
    # The whole catalog, not a condensed retype. A compressed copy once dropped the
    # "strongest discriminators" paragraph and the model began reporting model-tiering
    # as ABSENT on dips that used it.
    assert call["system"] == DIP_CATALOG
    assert "strongest discriminators" in call["system"].lower()
    assert "workflow Demo {}" in call["messages"][0]["content"]


def test_node_level_forbids_run_level_judgement():
    relay = FakeRelay()
    make_summarize_fn(relay, "gemma4:26b")("node", content="ran tests")
    system = relay.calls[0]["system"]
    # Node summaries must stay node-local: a run does not know whether it succeeded, so
    # inviting a verdict here would manufacture a judgement the corpus lacks.
    assert "Do NOT judge overall run success" in system
    assert "MUST appear in the trace" in system


def test_deterministic_and_raises_ollama_context():
    relay = FakeRelay()
    make_summarize_fn(relay, "gemma4:26b")("node", content="x")
    call = relay.calls[0]
    assert call["temperature"] == 0.0  # re-running a corpus reproduces its summaries
    # Ollama truncates long prompts SILENTLY from the left at its small default
    # context; a node trace overflows it, so num_ctx must be raised explicitly.
    assert call["ollama_options"]["num_ctx"] >= 8192
    assert call["model"] == "gemma4:26b"


def test_unknown_level_raises():
    with pytest.raises(ValueError, match="unknown summarization level"):
        make_summarize_fn(FakeRelay(), "m")("rollup", content="x")


def test_text_is_stripped():
    relay = FakeRelay(text="  padded  ")
    assert make_summarize_fn(relay, "m")("dip", content="x") == "padded"
