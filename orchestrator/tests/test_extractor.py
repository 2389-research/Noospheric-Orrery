# ABOUTME: Tests for the entity extraction pipeline function.
# ABOUTME: Verifies entity extraction from chunks using a mocked Relay instance.

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.extractor import extract_entities_from_chunk


@pytest.mark.asyncio
async def test_extract_entities_returns_list():
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "entities": [
            {"name": "wet blending", "type": "Technique"},
            {"name": "Duncan Rhodes", "type": "Person"},
        ]
    })

    mock_relay = AsyncMock()
    mock_relay.complete = AsyncMock(return_value=mock_response)

    entities = await extract_entities_from_chunk(
        relay=mock_relay,
        chunk_text="Duncan Rhodes demonstrates wet blending...",
        spec="Extract entities: Person, Technique, Thing from this text.",
        model="claude-haiku-4-5",
    )

    assert len(entities) == 2
    assert entities[0]["name"] == "wet blending"
    assert entities[0]["type"] == "Technique"
