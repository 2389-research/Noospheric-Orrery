"""Document reader endpoint — returns chunks with entity spans computed via string matching."""

import re
from fastapi import APIRouter, HTTPException, Depends
from ..dependencies import get_auth_store, AuthStore, query_id
from ..repositories.factory import get_store

router = APIRouter()


def _find_entity_spans(text: str, entities: list[dict]) -> list[dict]:
    """Find all entity mentions in text via case-insensitive string matching."""
    spans = []
    text_lower = text.lower()

    for entity in entities:
        names_to_try = [entity["canonical_name"]]
        names_to_try.extend(entity.get("merge_history", []))

        for name in names_to_try:
            if not name or len(name) < 2:
                continue
            escaped = re.escape(name.lower())
            pattern = r'(?<!\w)' + escaped + r'(?!\w)'
            for match in re.finditer(pattern, text_lower):
                spans.append({
                    "entity_id": entity["id"],
                    "entity_name": entity["canonical_name"],
                    "entity_type": entity["type"],
                    "start": match.start(),
                    "end": match.end(),
                    "is_new": entity.get("is_new", False),
                })

    spans.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))

    filtered = []
    last_end = 0
    for span in spans:
        if span["start"] >= last_end:
            filtered.append(span)
            last_end = span["end"]

    return filtered


def _build_segments(text: str, spans: list[dict]) -> list[dict]:
    """Build interleaved plain text + entity segments from text and spans."""
    segments = []
    pos = 0
    for span in spans:
        if span["start"] > pos:
            segments.append({"type": "text", "text": text[pos:span["start"]]})
        segments.append({
            "type": "entity", "text": text[span["start"]:span["end"]],
            "entity_id": span["entity_id"], "entity_name": span["entity_name"],
            "entity_type": span["entity_type"], "is_new": span.get("is_new", False),
        })
        pos = span["end"]
    if pos < len(text):
        segments.append({"type": "text", "text": text[pos:]})
    return segments


def _get_snippets(text: str, spans: list[dict], entity_id: str, max_chars: int = 200) -> list[str]:
    """Get context around each entity mention."""
    sentence_breaks = list(re.finditer(r'(?<=[.!?])\s+|\n\n|\n', text))
    sentence_starts = [0] + [m.end() for m in sentence_breaks]
    sentence_ends = [m.start() for m in sentence_breaks] + [len(text)]

    snippets = []
    seen = set()
    for span in spans:
        if span["entity_id"] != entity_id:
            continue
        snippet = None
        for i in range(len(sentence_starts)):
            if sentence_starts[i] <= span["start"] < sentence_ends[i]:
                sentence = text[sentence_starts[i]:sentence_ends[i]].strip()
                if len(sentence) <= max_chars:
                    snippet = sentence
                else:
                    half = max_chars // 2
                    start = max(sentence_starts[i], span["start"] - half)
                    end = min(sentence_ends[i], span["end"] + half)
                    snippet = text[start:end].strip()
                    if start > sentence_starts[i]:
                        snippet = "…" + snippet
                    if end < sentence_ends[i]:
                        snippet = snippet + "…"
                break
        if snippet and snippet not in seen:
            seen.add(snippet)
            snippets.append(snippet)
    return snippets[:3]


@router.get("/documents/{document_id}/reader")
def get_document_reader(document_id: str, auth: AuthStore = Depends(get_auth_store), qid: str = Depends(query_id)):
    """Return document content with entity spans for the reader view."""
    store = auth.store

    doc = store.documents.get(document_id)
    if not doc:
        store.close()
        raise HTTPException(status_code=404, detail="Document not found")

    # Get entities for this document with merge history
    entity_objs = store.entities.get_for_document(document_id)
    entities = []
    for e in entity_objs:
        merge_history = store.normalization.get_merge_history(e.id)
        entities.append({
            "id": e.id, "canonical_name": e.canonical_name, "type": e.type,
            "source_count": e.source_count, "merge_history": merge_history,
            "is_new": False,
        })

    # Get domains
    domain_assignments = store.domains.get_domains_for_document(document_id)
    domain_paths = [d.domain_path for d in domain_assignments]

    store.close()

    # Build text from content
    text = doc.content or ""

    # Find entity spans via string matching
    spans = _find_entity_spans(text, entities)

    # Build segments for rendering
    segments = _build_segments(text, spans)

    # Build per-entity mention data
    entity_mentions = {}
    for entity in entities:
        mentions_in_doc = [s for s in spans if s["entity_id"] == entity["id"]]
        snippets = _get_snippets(text, spans, entity["id"])
        entity_mentions[entity["id"]] = {
            "count": len(mentions_in_doc),
            "positions": [i / max(len(segments), 1) for i, seg in enumerate(segments) if seg.get("entity_id") == entity["id"]],
            "snippets": snippets,
        }

    return {
        "document": {
            "id": doc.id, "title": doc.title, "status": doc.status,
            "domains": domain_paths,
        },
        "entities": [
            {
                **entity,
                "mention_count": entity_mentions.get(entity["id"], {}).get("count", 0),
                "positions": entity_mentions.get(entity["id"], {}).get("positions", []),
                "snippets": entity_mentions.get(entity["id"], {}).get("snippets", []),
            }
            for entity in entities
            if entity_mentions.get(entity["id"], {}).get("count", 0) > 0
        ],
        "segments": segments,
        "total_mentions": len(spans),
        "query_id": qid,
    }
