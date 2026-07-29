from src.pipeline.chunker import chunk_document

def test_short_document_single_chunk():
    text = "This is a short document."
    chunks = chunk_document(text, chunk_size=2000)
    assert len(chunks) == 1
    assert chunks[0]["text"] == text
    assert chunks[0]["offset"] == 0
    assert chunks[0]["length"] == len(text)

def test_long_document_multiple_chunks():
    text = "word " * 1000  # 5000 chars
    chunks = chunk_document(text, chunk_size=2000)
    assert len(chunks) >= 2
    for i, chunk in enumerate(chunks):
        assert chunk["chunk_index"] == i
        assert chunk["text"] == text[chunk["offset"]:chunk["offset"] + chunk["length"]]

def test_chunks_have_overlap():
    text = "word " * 1000
    chunks = chunk_document(text, chunk_size=2000, overlap=200)
    if len(chunks) > 1:
        assert chunks[1]["offset"] < chunks[0]["offset"] + chunks[0]["length"]


import pytest
from unittest.mock import AsyncMock
from src.pipeline.chunker import chunk_by_sections


@pytest.mark.asyncio
async def test_chunk_by_sections_tags_each_chunk_and_preserves_offsets():
    text = "## Introduction\n" + ("intro word " * 300) + "\n\n## Method\n" + ("method word " * 300)
    mock_relay = AsyncMock()
    chunks = await chunk_by_sections(mock_relay, text, model="claude-haiku-4-5", chunk_size=500, overlap=50)

    assert len(chunks) > 1
    assert all("section" in c for c in chunks)
    assert chunks[0]["section"] == "introduction"
    assert chunks[-1]["section"] == "method"
    # chunk_index is continuous across the whole document
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    # offset/length still index into the ORIGINAL text
    for c in chunks:
        assert text[c["offset"]:c["offset"] + c["length"]] == c["text"]


@pytest.mark.asyncio
async def test_chunk_by_sections_no_headings_uses_llm_label_for_whole_doc():
    text = "word " * 300
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={"section": "method"})
    chunks = await chunk_by_sections(mock_relay, text, model="claude-haiku-4-5", chunk_size=500, overlap=50)
    assert all(c["section"] == "method" for c in chunks)
