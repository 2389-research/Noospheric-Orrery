# ABOUTME: Ollama-only kwargs (ollama_options, format) must reach the Ollama body
# ABOUTME: and must NOT reach the Anthropic SDK, whose create() rejects unknowns.

"""A caller cannot know which backend it is talking to.

`classify_document` passes `ollama_options={"num_ctx": ...}` on every call because
Ollama silently left-truncates an over-long prompt and there is no way to detect that
after the fact. The same call runs against Bedrock in production, and the Anthropic
SDK's `messages.create()` has a closed signature — an unknown keyword is a TypeError,
not an ignored hint. So the relay is the layer that has to sort them, and both halves
need pinning: dropped on the SDK path, *and* actually applied on the Ollama path (a
strip that also swallowed them on Ollama would fix the crash and reintroduce the
silent truncation).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_anthropic_message():
    msg = MagicMock()
    msg.content = [MagicMock(text="ok")]
    msg.usage = MagicMock(input_tokens=1, output_tokens=1)
    return msg


@pytest.mark.asyncio
@pytest.mark.parametrize("backend,client_kwargs", [
    ("gateway", {"gateway_url": "https://gw.test", "gateway_api_key": "k"}),
    ("bedrock", {"aws_access_key": "ak", "aws_secret_key": "sk", "aws_region": "us-east-1"}),
])
async def test_ollama_only_kwargs_never_reach_the_anthropic_sdk(backend, client_kwargs):
    from orrery_relay import Relay
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_mock_anthropic_message())
    with patch("orrery_relay.relay.create_async_client", return_value=mock_client):
        relay = Relay(backend=backend, **client_kwargs)
        await relay.complete(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=100,
            ollama_options={"num_ctx": 16384},
            format={"type": "object"},
        )
    sent = mock_client.messages.create.call_args[1]
    assert "ollama_options" not in sent
    assert "format" not in sent
    # A genuine passthrough kwarg must still get through — the filter is an
    # allow-by-default list, not a general kwargs blocker.
    assert sent["max_tokens"] == 100


def test_ollama_only_kwargs_never_reach_the_sync_sdk_call():
    from orrery_relay import Relay
    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=_mock_anthropic_message())
    with patch("orrery_relay.relay.create_sync_client", return_value=mock_client):
        relay = Relay(backend="gateway", gateway_url="https://gw.test", gateway_api_key="k")
        relay.complete_sync(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=100,
            ollama_options={"num_ctx": 16384},
        )
    assert "ollama_options" not in mock_client.messages.create.call_args[1]


@pytest.mark.asyncio
async def test_ollama_options_are_merged_into_the_request_body():
    """The other half: on Ollama they must actually take effect.

    Merged into `options` alongside num_predict/temperature rather than replacing it —
    overwriting the dict would drop the output-token budget.
    """
    from orrery_relay import Relay

    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "{}"}, "prompt_eval_count": 1, "eval_count": 1}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            captured.update(json or {})
            return _Resp()

    with patch("httpx.AsyncClient", lambda **kw: _Client()):
        relay = Relay(backend="ollama", ollama_url="http://localhost:11434")
        await relay.complete(
            model="gemma4:26b",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=512,
            temperature=0.2,
            ollama_options={"num_ctx": 16384},
        )

    assert captured["options"]["num_ctx"] == 16384
    assert captured["options"]["num_predict"] == 512, "num_ctx overwrote the token budget"
    assert captured["options"]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_structured_output_on_ollama_uses_native_grammar_constraint():
    """The schema goes in `format`, which makes Ollama grammar-constrain decoding.

    Spelling the schema out in the prompt only *asked* for valid JSON, and cost tokens
    on the same context that gets truncated. `format` makes malformed JSON
    unrepresentable instead.
    """
    from orrery_relay import Relay

    captured = {}
    schema = {"type": "object", "properties": {"primary_domain": {"type": "string"}}}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": '{"primary_domain": "a/b/c"}'},
                                "prompt_eval_count": 1, "eval_count": 1}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            captured.update(json or {})
            return _Resp()

    with patch("httpx.AsyncClient", lambda **kw: _Client()):
        relay = Relay(backend="ollama", ollama_url="http://localhost:11434")
        result = await relay.complete_structured(
            model="gemma4:26b",
            messages=[{"role": "user", "content": "classify this"}],
            max_tokens=512,
            schema=schema,
            ollama_options={"num_ctx": 16384},
        )

    assert captured["format"] == schema
    assert captured["options"]["num_ctx"] == 16384, (
        "complete_structured dropped ollama_options on the way to _complete_ollama")
    assert result == {"primary_domain": "a/b/c"}
    # The full schema is no longer pasted into the prompt — that was the token cost
    # this replaces.
    prompt = captured["messages"][-1]["content"]
    assert "properties" not in prompt
