"""Search endpoint — full staged pipeline."""

from fastapi import APIRouter, Depends
from ..config import get_settings
from ..dependencies import get_auth_store, AuthStore
from ..repositories.factory import get_store
from ..pipeline.search import search_knowledge_graph, build_indexes, embed_new_entities, embed_new_chunks
from ..broadcast import broadcast_search

router = APIRouter()


@router.get("/search")
async def search_query(q: str, top_k: int = 20, expand: bool = True, auth: AuthStore = Depends(get_auth_store)):
    settings = get_settings()
    store = auth.store
    response = await search_knowledge_graph(
        store.conn, q,  # pipeline still uses raw conn
        expand=expand,
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
        top_k=top_k,
    )
    store.close()

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
    store = auth.store
    new_entities = embed_new_entities(store.conn)
    new_chunks = embed_new_chunks(store.conn)
    stats = build_indexes(store.conn)
    store.close()
    return {"status": "rebuilt", "new_entities_embedded": new_entities,
            "new_chunks_embedded": new_chunks, **stats}
