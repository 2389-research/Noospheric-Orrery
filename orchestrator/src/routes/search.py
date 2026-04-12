# ABOUTME: Search route — 5-stage pipeline with FAISS on SQLite.
# ABOUTME: Supports query expansion via Relay, optional image search.

import numpy as np
from fastapi import APIRouter, Depends
from orrery_relay import Relay
from ..config import get_settings
from ..dependencies import get_auth_store, AuthStore
from ..broadcast import broadcast_search

router = APIRouter()


@router.get("/search")
async def search_query(q: str, top_k: int = 20, expand: bool = True, include_images: bool = False, auth: AuthStore = Depends(get_auth_store)):
    """Search the knowledge graph.

    Full 5-stage pipeline: expansion → retrieval → entity-boost → fusion → response.
    include_images=true adds parallel image search results.
    """
    settings = get_settings()
    store = auth.store
    relay = Relay.from_settings(settings)

    from ..pipeline.search import search_knowledge_graph
    result = await search_knowledge_graph(
        store.conn, q, expand=expand, relay=relay, top_k=top_k,
    )
    response = {
        "query": result.query,
        "entities": result.entities,
        "chunks": result.chunks,
        "sub_queries_used": result.sub_queries_used,
        "total_entities": result.total_entities,
        "total_chunks": result.total_chunks,
    }

    # Parallel image search (opt-in)
    if include_images:
        try:
            response["images"] = _search_images(store.conn, q, top_k=top_k)
        except Exception as e:
            print(f"Image search failed: {e}", flush=True)
            response["images"] = []

    store.close()

    # Broadcast to viz
    entity_names = [e["name"] for e in response.get("entities", [])[:10] if e.get("name")]
    if entity_names:
        await broadcast_search(q, entity_names)

    return response


def _search_images(conn, query: str, top_k: int = 10) -> list[dict]:
    """Search image documents by text similarity on descriptions.

    Falls back to SQL LIKE matching if no embeddings available.
    """
    # Try embedding-based search first
    try:
        from ..pipeline.search.retrieval import _get_model
        model = _get_model()
        query_emb = model.encode([query], normalize_embeddings=True)[0]

        rows = conn.execute("""
            SELECT c.id, c.text, c.embedding, d.id as doc_id, d.title, d.source_path
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.content_type = 'image' AND c.embedding IS NOT NULL
        """).fetchall()

        if rows:
            scored = []
            for row in rows:
                emb = np.frombuffer(row[2], dtype=np.float32)
                sim = float(np.dot(query_emb, emb) / (np.linalg.norm(query_emb) * np.linalg.norm(emb) + 1e-8))
                scored.append({
                    "document_id": row[3],
                    "title": row[4],
                    "description": (row[1] or "")[:200],
                    "score": round(sim, 3),
                })
            scored.sort(key=lambda x: -x["score"])
            return scored[:top_k]
    except Exception:
        pass

    # Fallback: SQL LIKE on description text
    query_like = f"%{query}%"
    rows = conn.execute("""
        SELECT d.id, d.title, c.text
        FROM documents d
        JOIN chunks c ON c.document_id = d.id
        WHERE d.content_type = 'image' AND c.text LIKE ?
        LIMIT ?
    """, (query_like, top_k)).fetchall()

    return [{"document_id": r[0], "title": r[1], "description": (r[2] or "")[:200], "score": 1.0} for r in rows]


@router.post("/search/rebuild")
def rebuild_search_index(auth: AuthStore = Depends(get_auth_store)):
    """Rebuild FAISS search indexes — re-embeds entities and chunks missing embeddings."""
    store = auth.store

    from ..pipeline.search import build_indexes, embed_new_entities, embed_new_chunks
    new_entities = embed_new_entities(store.conn)
    new_chunks = embed_new_chunks(store.conn)
    stats = build_indexes(store.conn)
    store.close()
    return {"status": "rebuilt", "new_entities_embedded": new_entities, "new_chunks_embedded": new_chunks, **stats}
