"""Search endpoint — full staged pipeline."""

from fastapi import APIRouter
from ..config import get_settings
from ..db import get_connection
from ..pipeline.search import search_knowledge_graph, build_indexes, embed_new_entities, embed_new_chunks
from ..broadcast import broadcast_search

router = APIRouter()


@router.get("/search")
async def search_query(q: str, top_k: int = 20, expand: bool = True):
    """Search the knowledge graph. Broadcasts results to viz clients."""
    settings = get_settings()
    conn = get_connection(settings.db_path)

    response = await search_knowledge_graph(
        conn, q,
        expand=expand,
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
        top_k=top_k,
    )
    conn.close()

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
def rebuild_search_index():
    """Rebuild FAISS indexes and embed any unembedded entities/chunks."""
    settings = get_settings()
    conn = get_connection(settings.db_path)
    new_entities = embed_new_entities(conn)
    new_chunks = embed_new_chunks(conn)
    stats = build_indexes(conn)
    conn.close()
    return {"status": "rebuilt", "new_entities_embedded": new_entities, "new_chunks_embedded": new_chunks, **stats}
