"""Search endpoint — FAISS on SQLite, Firestore vector search on Firestore."""

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
        # Firestore: vector search via Vertex AI embeddings
        result = await _vector_search(store, q, top_k, settings)
        store.close()

    entity_names = [e["name"] for e in result.get("entities", [])[:10] if e.get("name")]
    if entity_names:
        await broadcast_search(q, entity_names)

    return result


async def _vector_search(store, query: str, top_k: int, settings) -> dict:
    """Firestore vector search using Vertex AI embeddings."""
    try:
        from ..services.embedding import embed_text
        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
        from google.cloud.firestore_v1.vector import Vector

        # Embed the query
        query_embedding = embed_text(query)

        # Search entities
        entity_col = store._entities._col
        entity_results = entity_col.find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_embedding),
            distance_measure=DistanceMeasure.COSINE,
            limit=top_k,
        ).get()

        entities = []
        for doc in entity_results:
            d = doc.to_dict()
            entities.append({
                "id": doc.id,
                "name": d.get("canonicalName", ""),
                "type": d.get("type", ""),
                "score": round(d.get("distance", 0), 3),
                "source_count": d.get("sourceCount", 0),
                "paths": [],
                "appearances": [],
            })

        # Search chunks
        chunk_col = store._chunks._col
        chunk_results = chunk_col.find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_embedding),
            distance_measure=DistanceMeasure.COSINE,
            limit=min(top_k, 10),
        ).get()

        chunks = []
        for doc in chunk_results:
            d = doc.to_dict()
            chunks.append({
                "chunk_id": doc.id,
                "document_id": d.get("documentId", ""),
                "document_title": "",
                "text": d.get("text", "")[:300],
                "score": round(d.get("distance", 0), 3),
                "entity_overlap": [],
            })

        return {
            "query": query,
            "entities": entities,
            "chunks": chunks,
            "sub_queries_used": [query],
            "total_entities": len(entities),
            "total_chunks": len(chunks),
        }

    except Exception as e:
        print(f"Vector search failed, falling back to keyword: {e}")
        return _keyword_search(store, query, top_k)


def _keyword_search(store, query: str, top_k: int = 20) -> dict:
    """Fallback keyword search — name matching on entities."""
    query_lower = query.lower().strip()
    terms = query_lower.split()

    all_entities = store.entities.list(limit=2000)
    matched = []
    for e in all_entities:
        name_lower = e.canonical_name.lower()
        if name_lower == query_lower:
            score = 1.0
        elif all(t in name_lower for t in terms):
            score = 0.8
        elif any(t in name_lower for t in terms):
            score = 0.5
        else:
            continue
        matched.append({
            "id": e.id, "name": e.canonical_name, "type": e.type,
            "score": round(score, 3), "source_count": e.source_count,
            "paths": [], "appearances": [],
        })

    matched.sort(key=lambda e: (-e["score"], -e["source_count"]))
    return {
        "query": query, "entities": matched[:top_k], "chunks": [],
        "sub_queries_used": [query],
        "total_entities": len(matched), "total_chunks": 0,
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
    return {"status": "ok", "note": "Firestore uses vector search — embeddings stored on ingest"}
