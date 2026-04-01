# ABOUTME: Search route — exposes the staged search pipeline over HTTP.
# ABOUTME: Supports query expansion via Relay and broadcasts results to viz clients.

from fastapi import APIRouter, Depends
from orrery_relay import Relay
from ..config import get_settings
from ..dependencies import get_auth_store, AuthStore
from ..pipeline.search import search_knowledge_graph, build_indexes, embed_new_entities, embed_new_chunks
from ..broadcast import broadcast_search

router = APIRouter()


@router.get("/search")
async def search_query(q: str, top_k: int = 20, expand: bool = True, auth: AuthStore = Depends(get_auth_store)):
    """Search the knowledge graph. Broadcasts results to viz clients."""
    settings = get_settings()
    store = auth.store

    relay = Relay.from_settings(settings)
    response = await search_knowledge_graph(
        store.conn, q,
        expand=expand,
        relay=relay,
        top_k=top_k,
    )
    store.close()

    # Broadcast to viz
    entity_names = [e["name"] for e in response.entities[:10] if e.get("name")]
    if entity_names:
        await broadcast_search(q, entity_names)

    return {
        "query": response.query,
        "entities": response.entities,
        "chunks": response.chunks,
        "sub_queries_used": response.sub_queries_used,
        "total_entities": response.total_entities,
        "total_chunks": response.total_chunks,
    }


@router.post("/search/rebuild")
def rebuild_search_index(auth: AuthStore = Depends(get_auth_store)):
    """Rebuild FAISS indexes and embed any unembedded entities/chunks."""
    store = auth.store
    new_entities = embed_new_entities(store.conn)
    new_chunks = embed_new_chunks(store.conn)
    stats = build_indexes(store.conn)
    store.close()
    return {"status": "rebuilt", "new_entities_embedded": new_entities, "new_chunks_embedded": new_chunks, **stats}
