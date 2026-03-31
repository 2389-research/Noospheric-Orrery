"""Search endpoint — full staged pipeline on SQLite, simple search on Firestore."""

from __future__ import annotations
from fastapi import APIRouter, Depends
from ..config import get_settings
from ..dependencies import get_auth_store, AuthStore
from ..repositories.factory import get_store
from ..broadcast import broadcast_search

router = APIRouter()


@router.get("/search")
async def search_query(q: str, top_k: int = 20, expand: bool = True, auth: AuthStore = Depends(get_auth_store)):
    settings = get_settings()
    store = auth.store

    if store.conn is not None:
        # SQLite: full FAISS pipeline
        from ..pipeline.search import search_knowledge_graph
        response = await search_knowledge_graph(
            store.conn, q, expand=expand,
            aws_access_key=settings.aws_access_key,
            aws_secret_key=settings.aws_secret_key,
            aws_region=settings.aws_region,
            top_k=top_k,
        )
        store.close()
        result = {
            "query": response.query,
            "entities": response.entities,
            "chunks": response.chunks,
            "sub_queries_used": response.sub_queries_used,
            "total_entities": response.total_entities,
            "total_chunks": response.total_chunks,
        }
    else:
        # Firestore: simple name-match search
        result = _simple_search(store, q, top_k)
        store.close()

    entity_names = [e["name"] for e in result.get("entities", [])[:10] if e.get("name")]
    if entity_names:
        await broadcast_search(q, entity_names)

    return result


def _simple_search(store, query: str, top_k: int = 20) -> dict:
    """Simple search for Firestore — name matching on entities + doc title matching."""
    query_lower = query.lower().strip()
    terms = query_lower.split()

    # Search entities by name
    all_entities = store.entities.list(limit=2000)
    matched_entities = []
    for e in all_entities:
        name_lower = e.canonical_name.lower()
        # Score: exact match > contains all terms > contains any term
        if name_lower == query_lower:
            score = 1.0
        elif all(t in name_lower for t in terms):
            score = 0.8
        elif any(t in name_lower for t in terms):
            score = 0.5
        else:
            continue
        matched_entities.append({
            "id": e.id, "name": e.canonical_name, "type": e.type,
            "score": round(score, 3), "source_count": e.source_count,
            "paths": [], "appearances": [],
        })

    matched_entities.sort(key=lambda e: (-e["score"], -e["source_count"]))
    matched_entities = matched_entities[:top_k]

    # Search documents by title
    all_docs = store.documents.list(limit=500)
    matched_chunks = []
    for d in all_docs:
        title_lower = (d.title or "").lower()
        if any(t in title_lower for t in terms):
            matched_chunks.append({
                "chunk_id": "", "document_id": d.id,
                "document_title": d.title, "text": d.title,
                "score": 0.5, "entity_overlap": [],
            })

    return {
        "query": query,
        "entities": matched_entities,
        "chunks": matched_chunks[:10],
        "sub_queries_used": [query],
        "total_entities": len(matched_entities),
        "total_chunks": len(matched_chunks),
    }


@router.post("/search/rebuild")
def rebuild_search_index(auth: AuthStore = Depends(get_auth_store)):
    store = auth.store
    if store.conn is not None:
        from ..pipeline.search.retrieval import embed_new_entities, embed_new_chunks, build_indexes
        new_entities = embed_new_entities(store.conn)
        new_chunks = embed_new_chunks(store.conn)
        stats = build_indexes(store.conn)
        store.close()
        return {"status": "rebuilt", "new_entities_embedded": new_entities,
                "new_chunks_embedded": new_chunks, **stats}
    store.close()
    return {"status": "ok", "note": "Firestore uses simple search — no index rebuild needed"}
