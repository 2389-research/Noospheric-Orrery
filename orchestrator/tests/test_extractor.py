# ABOUTME: Tests for the entity extraction pipeline function.
# ABOUTME: Verifies entity extraction from chunks using a mocked Relay instance.

import pytest
from unittest.mock import AsyncMock
from src.pipeline.extractor import extract_entities_from_chunk, extract_document_sectioned


@pytest.mark.asyncio
async def test_extract_entities_returns_list():
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={
        "entities": [
            {"name": "wet blending", "type": "Technique"},
            {"name": "Duncan Rhodes", "type": "Person"},
        ]
    })

    entities = await extract_entities_from_chunk(
        relay=mock_relay,
        chunk_text="Duncan Rhodes demonstrates wet blending...",
        spec="Extract entities: Person, Technique, Thing from this text.",
        model="claude-haiku-4-5",
    )

    assert len(entities) == 2
    assert entities[0]["name"] == "wet blending"
    assert entities[0]["type"] == "Technique"
    mock_relay.complete_structured.assert_called_once()


@pytest.mark.asyncio
async def test_extract_document_sectioned_picks_spec_by_chunk_section():
    mock_relay = AsyncMock()

    async def fake_complete_structured(model, max_tokens, messages, schema, tool_name, tool_description):
        prompt = messages[0]["content"]
        if "INTRO-ONLY-MARKER" in prompt:
            return {"entities": [{"name": "hero model", "type": "model"}]}
        return {"entities": [{"name": "some method", "type": "method"}]}

    mock_relay.complete_structured = AsyncMock(side_effect=fake_complete_structured)

    chunks = [
        {"id": "c1", "text": "We propose the hero model.", "section": "introduction"},
        {"id": "c2", "text": "The method combines two losses.", "section": "method"},
    ]
    section_specs = {
        "introduction": "INTRO-ONLY-MARKER extraction spec",
        "method": "method extraction spec",
        "default": "default extraction spec",
    }

    entities = await extract_document_sectioned(
        relay=mock_relay, chunks=chunks, section_specs=section_specs, model="claude-haiku-4-5",
    )

    assert {"name": "hero model", "type": "model", "chunk_id": "c1"} in entities
    assert {"name": "some method", "type": "method", "chunk_id": "c2"} in entities


@pytest.mark.asyncio
async def test_extract_document_sectioned_falls_back_to_default_for_unknown_section():
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={"entities": [{"name": "x", "type": "model"}]})
    chunks = [{"id": "c1", "text": "text", "section": "unclassified"}]
    section_specs = {"introduction": "intro spec", "default": "DEFAULT-MARKER spec"}

    await extract_document_sectioned(
        relay=mock_relay, chunks=chunks, section_specs=section_specs, model="claude-haiku-4-5",
    )

    call_kwargs = mock_relay.complete_structured.call_args.kwargs
    assert "DEFAULT-MARKER" in call_kwargs["messages"][0]["content"]
