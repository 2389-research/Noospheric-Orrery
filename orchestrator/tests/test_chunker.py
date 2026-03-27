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
