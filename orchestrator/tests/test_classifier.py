import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.pipeline.classifier import classify_document

@pytest.mark.asyncio
async def test_classify_returns_domains():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "primary_domain": "techniques/wet-blending",
        "secondary_domains": ["theory/color-theory"],
        "new_domains": [],
        "confidence": 0.9,
    }))]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    result = await classify_document(
        client=mock_client,
        title="Wet Blending Tutorial",
        excerpt="How to wet blend on miniatures...",
        existing_taxonomy=["techniques", "theory"],
        model="claude-sonnet-4-20250514",
    )

    assert result["primary_domain"] == "techniques/wet-blending"
    assert "theory/color-theory" in result["secondary_domains"]
    mock_client.messages.create.assert_called_once()
