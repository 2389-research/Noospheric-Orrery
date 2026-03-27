import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.extractor import extract_entities_from_chunk

@pytest.mark.asyncio
async def test_extract_entities_returns_list():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "entities": [
            {"name": "wet blending", "type": "Technique"},
            {"name": "Duncan Rhodes", "type": "Person"},
        ]
    }))]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    entities = await extract_entities_from_chunk(
        client=mock_client,
        chunk_text="Duncan Rhodes demonstrates wet blending...",
        spec="Extract entities: Person, Technique, Thing from this text.",
        model="claude-haiku-4-20250514",
    )

    assert len(entities) == 2
    assert entities[0]["name"] == "wet blending"
    assert entities[0]["type"] == "Technique"
