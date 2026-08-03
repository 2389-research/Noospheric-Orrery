from .section_splitter import label_sections


def chunk_document(text: str, chunk_size: int = 2000, overlap: int = 200) -> list[dict]:
    if len(text) <= chunk_size:
        return [{"chunk_index": 0, "offset": 0, "length": len(text), "text": text}]
    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append({"chunk_index": idx, "offset": start, "length": end - start, "text": text[start:end]})
        idx += 1
        start = end - overlap if end < len(text) else end
    return chunks


async def chunk_by_sections(relay, text: str, model: str, chunk_size: int = 2000, overlap: int = 200) -> list[dict]:
    spans = await label_sections(relay, text, model)
    all_chunks = []
    idx = 0
    for span in spans:
        span_text = text[span["start"]:span["end"]]
        if not span_text:
            continue
        for chunk in chunk_document(span_text, chunk_size=chunk_size, overlap=overlap):
            all_chunks.append({
                "chunk_index": idx,
                "offset": span["start"] + chunk["offset"],
                "length": chunk["length"],
                "text": chunk["text"],
                "section": span["section"],
            })
            idx += 1
    return all_chunks
