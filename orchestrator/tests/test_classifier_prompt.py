"""What `classify_document` actually sends, as opposed to what it gets back.

`test_classifier.py` mocks the relay and checks the parsed result, so it passes
regardless of whether the prompt was assembled correctly. Everything asserted here
is a property of the *request* — and each one, if wrong, fails silently: the model
still answers, the answer still parses, and the only symptom is a graph that
gradually fills with near-duplicate domain paths.
"""

import pytest
from unittest.mock import AsyncMock

from src.pipeline import classifier
from src.pipeline.classifier import CLASSIFICATION_SCHEMA, classify_document


def _sent(mock) -> dict:
    """The kwargs of the single relay call."""
    assert mock.complete_structured.await_count == 1
    return mock.complete_structured.await_args.kwargs


async def _classify(taxonomy=("software/backend/rest-api",), excerpt="a summary") -> dict:
    mock = AsyncMock()
    mock.complete_structured = AsyncMock(return_value={
        "primary_domain": "software/backend/rest-api",
        "secondary_domains": [],
        "confidence": 0.9,
    })
    await classify_document(
        relay=mock, title="t", excerpt=excerpt,
        existing_taxonomy=list(taxonomy), model="claude-sonnet-4-6",
    )
    return _sent(mock)


@pytest.mark.asyncio
async def test_the_reference_vocabulary_is_actually_in_the_prompt():
    """The vocabulary is the mechanism that makes equivalent content converge.

    Without it the model invents a fresh path per document (`llm_agents` beside
    `llm-orchestration` beside `agent-coordination`), and those are separate nodes —
    the graph silently fragments rather than erroring.
    """
    blocks = (await _classify())["messages"][0]["content"]
    prompt = "\n".join(b["text"] for b in blocks)
    assert "REFERENCE VOCABULARY" in prompt
    # Real entries from specs/taxonomy.json, not just the header.
    assert "llm-orchestration" in prompt
    assert "software/ai-agents" in prompt
    assert "people/hiring" in prompt


@pytest.mark.asyncio
async def test_the_cache_breakpoint_sits_before_the_growing_taxonomy():
    """Caching only pays if the cached prefix is byte-identical between calls.

    The existing-taxonomy block changes every time a domain is added, so marking it
    cacheable would invalidate the entry on essentially every call — paying the 1.25x
    write premium forever and never taking a read. So: exactly one marked block, it is
    the first, and the taxonomy is NOT in it.
    """
    # A sentinel, not a real path: the static prompt cites real paths as worked
    # examples, so a real one would be found in both blocks and prove nothing.
    sentinel = "zzz-sentinel/not-a-real/domain"
    blocks = (await _classify(taxonomy=[sentinel]))["messages"][0]["content"]
    marked = [i for i, b in enumerate(blocks) if "cache_control" in b]
    assert marked == [0], f"expected exactly the first block marked, got {marked}"
    assert "REFERENCE VOCABULARY" in blocks[0]["text"]
    assert sentinel not in blocks[0]["text"], (
        "the existing taxonomy leaked into the cached block — it changes as the graph "
        "grows, so every call would miss the cache")
    assert sentinel in blocks[1]["text"]


@pytest.mark.asyncio
async def test_the_static_block_does_not_vary_with_the_document():
    """Two different documents must produce the SAME cached block, byte for byte."""
    a = (await _classify(taxonomy=["a/b/c"], excerpt="one"))["messages"][0]["content"][0]
    b = (await _classify(taxonomy=["x/y/z"], excerpt="two"))["messages"][0]["content"][0]
    assert a["text"] == b["text"]


@pytest.mark.asyncio
async def test_ollama_gets_a_context_window_large_enough_for_the_prompt():
    """Ollama truncates an over-long prompt from the LEFT and reports nothing.

    Left-truncation is the bad direction: it discards the instructions and the
    reference vocabulary and keeps the excerpt, so the model answers from the
    document alone. The response is still well-formed and still parses — the request
    is the only place this is visible, which is why it is asserted here.
    """
    # Assert on the prompt's real size rather than a remembered number, so this
    # stays true as the prompt changes.
    sent = await _classify()
    blocks = sent["messages"][0]["content"]
    prompt_chars = sum(len(b["text"]) for b in blocks)
    num_ctx = sent["ollama_options"]["num_ctx"]

    assert num_ctx > 4096, "no point overriding the default with the default"
    # ~4 chars/token is the standard rough ratio; leave room for the response too.
    approx_tokens = prompt_chars / 4
    assert num_ctx > approx_tokens + sent.get("max_tokens", 1024), (
        f"num_ctx={num_ctx} does not cover a ~{approx_tokens:.0f}-token prompt plus its "
        f"response; Ollama would silently drop the head of the prompt")


@pytest.mark.asyncio
async def test_subdomains_are_requested_so_files_can_be_placed_individually():
    """Repo ingest spreads a repo's files across its internal facets by matching each
    file summary to a subdomain. If the schema stops offering `subdomains`, that
    placement degrades to "every file inherits the repo's one domain" — and it
    degrades quietly, because the caller treats a missing list as "none found".
    """
    assert "subdomains" in CLASSIFICATION_SCHEMA["properties"]
    prompt = "\n".join(b["text"] for b in (await _classify())["messages"][0]["content"])
    assert "SUBDOMAINS" in prompt
    # Optional on purpose: a plain document has none, and requiring it would force
    # the model to invent facets for a one-page note.
    assert "subdomains" not in CLASSIFICATION_SCHEMA["required"]


def test_the_two_prompt_halves_compose_into_the_back_compat_constant():
    """`CLASSIFICATION_PROMPT` is still exported for ad-hoc renders; keep it real."""
    assert classifier.CLASSIFICATION_PROMPT == (
        classifier.CLASSIFICATION_PROMPT_STATIC + "\n\n" + classifier.CLASSIFICATION_PROMPT_DYNAMIC)
