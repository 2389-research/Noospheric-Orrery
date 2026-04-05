# ABOUTME: Tests for the document classifier pipeline function.
# ABOUTME: Verifies domain classification using a mocked Relay instance.

import pytest
from unittest.mock import AsyncMock
from src.pipeline.classifier import classify_document


@pytest.mark.asyncio
async def test_classify_returns_domains():
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={
        "primary_domain": "techniques/wet-blending",
        "secondary_domains": ["theory/color-theory"],
        "confidence": 0.9,
    })

    result = await classify_document(
        relay=mock_relay,
        title="Wet Blending Tutorial",
        excerpt="How to wet blend on miniatures...",
        existing_taxonomy=["techniques", "theory"],
        model="claude-sonnet-4-6",
    )

    assert result["primary_domain"] == "techniques/wet-blending"
    assert "theory/color-theory" in result["secondary_domains"]
    mock_relay.complete_structured.assert_called_once()
