# ABOUTME: Tests for the document classifier pipeline function.
# ABOUTME: Verifies domain classification using a mocked Relay instance.

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.classifier import classify_document


@pytest.mark.asyncio
async def test_classify_returns_domains():
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "primary_domain": "techniques/wet-blending",
        "secondary_domains": ["theory/color-theory"],
        "new_domains": [],
        "confidence": 0.9,
    })

    mock_relay = AsyncMock()
    mock_relay.complete = AsyncMock(return_value=mock_response)

    result = await classify_document(
        relay=mock_relay,
        title="Wet Blending Tutorial",
        excerpt="How to wet blend on miniatures...",
        existing_taxonomy=["techniques", "theory"],
        model="claude-sonnet-4-6",
    )

    assert result["primary_domain"] == "techniques/wet-blending"
    assert "theory/color-theory" in result["secondary_domains"]
    mock_relay.complete.assert_called_once()
