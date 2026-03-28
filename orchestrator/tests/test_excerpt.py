from src.pipeline.excerpt import build_classification_excerpt

def test_short_doc_returns_full():
    text = "Short document content."
    excerpt = build_classification_excerpt("My Title", text)
    assert "My Title" in excerpt
    assert "Short document content." in excerpt

def test_long_doc_samples_three_windows():
    text = "A" * 3000 + "B" * 3000 + "C" * 3000
    excerpt = build_classification_excerpt("Title", text)
    assert "Title" in excerpt
    assert "A" in excerpt
    assert "B" in excerpt
    assert "C" in excerpt
    assert len(excerpt) < len(text)

def test_medium_doc_returns_full():
    text = "Content " * 500  # ~4K chars
    excerpt = build_classification_excerpt("Title", text)
    assert text in excerpt
