"""Tests for UMAP domain layout with anchor domains."""

import json
from pathlib import Path
from unittest.mock import patch
import numpy as np


def test_anchor_domains_load():
    """Universal domains JSON loads correctly."""
    from src.pipeline.domain_layout import _get_anchor_domains
    anchors = _get_anchor_domains()
    assert len(anchors) == 100
    assert "business/startups/product-market-fit" in anchors
    assert "science/physics/quantum-mechanics" in anchors


def test_full_fit_with_anchors(test_store):
    """full_fit includes anchor domains for well-distributed space."""
    # Add 3 domains with docs
    for i, path in enumerate(["tech/ai", "tech/ml", "art/painting"]):
        test_store.conn.execute(
            "INSERT INTO domains (id, path, document_count) VALUES (?, ?, 2)",
            (f"d{i}", path),
        )
    test_store.conn.commit()

    import umap as umap_module

    with patch("src.pipeline.domain_layout._embed_texts") as mock_embed:
        def fake_embed(texts):
            return np.random.rand(len(texts), 10).astype(np.float32)
        mock_embed.side_effect = fake_embed

        # Patch umap.UMAP — use a real UMAP but with small data
        from src.pipeline.domain_layout import full_fit
        positions = full_fit(test_store)

    # Should have positions for user domains only (not anchors)
    assert len(positions) == 3
    assert "tech/ai" in positions
    assert "tech/ml" in positions
    assert "art/painting" in positions
    # Positions should be 0-1
    for pos in positions.values():
        assert 0 <= pos["x"] <= 1
        assert 0 <= pos["y"] <= 1


def test_ensure_layout_returns_stored(test_store):
    """ensure_layout returns stored positions without recomputing."""
    test_store.conn.execute(
        "INSERT INTO domains (id, path, document_count) VALUES ('d1', 'test/domain', 2)"
    )
    test_store.conn.execute(
        "INSERT INTO domain_layout (domain_path, x, y) VALUES ('test/domain', 0.5, 0.7)"
    )
    test_store.conn.commit()

    from src.pipeline.domain_layout import ensure_layout
    positions = ensure_layout(test_store)
    assert positions["test/domain"]["x"] == 0.5
    assert positions["test/domain"]["y"] == 0.7


def test_ensure_layout_removes_stale(test_store):
    """ensure_layout removes positions for domains that no longer exist."""
    # Domain exists but has 0 docs (not active)
    test_store.conn.execute(
        "INSERT INTO domains (id, path, document_count) VALUES ('d1', 'old/domain', 0)"
    )
    test_store.conn.execute(
        "INSERT INTO domain_layout (domain_path, x, y) VALUES ('old/domain', 0.5, 0.7)"
    )
    test_store.conn.commit()

    from src.pipeline.domain_layout import ensure_layout
    positions = ensure_layout(test_store)
    assert "old/domain" not in positions
