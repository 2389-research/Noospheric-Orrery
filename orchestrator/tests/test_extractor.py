# ABOUTME: Tests for the entity extraction pipeline function.
# ABOUTME: Verifies entity extraction from chunks using a mocked Relay instance.

import pytest
from unittest.mock import AsyncMock
from src.pipeline.extractor import extract_entities_from_chunk


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
async def test_extract_entities_tolerates_bare_list():
    """Issue #36: the Anthropic/gateway backend intermittently returns the entities
    array at the top level instead of {"entities": [...]}. It must not crash."""
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value=[
        {"name": "wet blending", "type": "Technique"},
        {"name": "Duncan Rhodes", "type": "Person"},
    ])

    entities = await extract_entities_from_chunk(
        relay=mock_relay,
        chunk_text="Duncan Rhodes demonstrates wet blending...",
        spec="Extract entities: Person, Technique, Thing from this text.",
        model="claude-haiku-4-5",
    )

    assert len(entities) == 2
    assert entities[0]["name"] == "wet blending"
