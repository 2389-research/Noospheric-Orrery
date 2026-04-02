# ABOUTME: Search route — 5-stage pipeline with Firestore vector search or FAISS on SQLite.
# ABOUTME: Supports query expansion via Relay. Used by both UI and MCP/agent queries.

import os
from fastapi import APIRouter, Depends
from orrery_relay import Relay
from ..config import get_settings
from ..dependencies import get_auth_store, AuthStore
from ..broadcast import broadcast_search

router = APIRouter()


@router.get("/search")
async def search_query(q: str, top_k: int = 20, expand: bool = True, auth: AuthStore = Depends(get_auth_store)):
    """Search the knowledge graph.

    Full 5-stage pipeline: expansion → retrieval → entity-boost → fusion → response.
    On Firestore: uses Vertex AI vector search for retrieval.
    On SQLite: uses FAISS for retrieval.
    expand=false skips LLM query expansion (faster, for UI autocomplete).
    """
    settings = get_settings()
    store = auth.store
    db_backend = os.environ.get("DB_BACKEND", "sqlite").lower()

    if db_backend == "firestore":
        response = await _firestore_search(store, q, top_k, expand, settings)
    else:
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

    store.close()

    # Broadcast to viz
    entity_names = [e["name"] for e in response.get("entities", [])[:10] if e.get("name")]
    if entity_names:
        await broadcast_search(q, entity_names)

    return response


async def _firestore_search(store, query: str, top_k: int, expand: bool, settings):
    """Full search pipeline on Firestore with Vertex AI vector retrieval."""
    from ..services.embedding import embed_text

    # Stage 0: Query expansion (optional — skipped for UI, enabled for agents)
    if expand:
        try:
            relay = Relay.from_settings(settings)
            from ..pipeline.search.expansion import expand_query
            sub_queries = await expand_query(relay=relay, query=query, max_sub_queries=3)
        except Exception:
            sub_queries = [query]
    else:
        sub_queries = [query]

    # Stage 1: Retrieval — vector search + exact match for each sub-query
    all_entity_hits = {}  # entity_id -> best score
    all_entity_data = {}  # entity_id -> entity dict

    for sq in sub_queries:
        # Vector search
        vector_hits = await _vector_search_entities(store, sq, top_k)
        for rank, ent in enumerate(vector_hits):
            eid = ent["id"]
            score = 1.0 / (rank + 1)  # RRF-style scoring
            if eid not in all_entity_hits or score > all_entity_hits[eid]:
                all_entity_hits[eid] = score
                all_entity_data[eid] = ent

        # Exact name match
        exact_hits = _exact_search_entities(store, sq)
        for ent in exact_hits:
            eid = ent["id"]
            score = 2.0  # Exact match gets priority
            if eid not in all_entity_hits or score > all_entity_hits[eid]:
                all_entity_hits[eid] = score
                all_entity_data[eid] = ent

    # Stage 2: Entity boost — entities with more sources rank higher
    for eid, ent in all_entity_data.items():
        source_boost = min(ent.get("source_count", 1) / 10, 1.0)
        all_entity_hits[eid] += source_boost * 0.3

    # Stage 3: Rank and collect
    ranked = sorted(all_entity_hits.items(), key=lambda x: -x[1])[:top_k]
    entities = []
    for eid, score in ranked:
        ent = all_entity_data[eid]
        ent["score"] = round(score, 3)
        entities.append(ent)

    # Stage 4: Get chunk context for top entities
    chunks = _get_chunk_context(store, [e["id"] for e in entities[:5]])

    return {
        "query": query,
        "entities": entities,
        "chunks": chunks,
        "sub_queries_used": sub_queries if len(sub_queries) > 1 else [],
        "total_entities": len(entities),
        "total_chunks": len(chunks),
    }


async def _vector_search_entities(store, query: str, top_k: int) -> list[dict]:
    """Vertex AI vector search on entity embeddings."""
    from ..services.embedding import embed_text
    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
    from google.cloud.firestore_v1.vector import Vector

    query_embedding = embed_text(query)
    entity_col = store._db.collection("workspaces").document(store._workspace_id).collection("entities")

    try:
        vector_query = entity_col.find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_embedding),
            distance_measure=DistanceMeasure.COSINE,
            limit=top_k,
        )
        results = []
        for doc in vector_query.stream():
            d = doc.to_dict()
            results.append({
                "id": doc.id,
                "name": d.get("canonicalName", ""),
                "type": d.get("type", "Thing"),
                "source_count": d.get("sourceCount", 0),
            })
        return results
    except Exception as e:
        print(f"Vector search failed: {e}", flush=True)
        return []


def _exact_search_entities(store, query: str) -> list[dict]:
    """Exact name prefix match on entities."""
    entity_col = store._db.collection("workspaces").document(store._workspace_id).collection("entities")
    name_lower = query.lower().strip()

    try:
        matches = list(entity_col
                       .where("canonicalName", ">=", name_lower)
                       .where("canonicalName", "<=", name_lower + "\uf8ff")
                       .limit(10).stream())
        return [{
            "id": doc.id,
            "name": doc.to_dict().get("canonicalName", ""),
            "type": doc.to_dict().get("type", "Thing"),
            "source_count": doc.to_dict().get("sourceCount", 0),
        } for doc in matches]
    except Exception:
        return []


def _get_chunk_context(store, entity_ids: list[str]) -> list[dict]:
    """Get source chunk text for top entities."""
    es_col = store._db.collection("workspaces").document(store._workspace_id).collection("entitySources")
    doc_col = store._db.collection("workspaces").document(store._workspace_id).collection("documents")
    chunk_col = store._db.collection("workspaces").document(store._workspace_id).collection("chunks")

    chunks = []
    seen = set()

    for eid in entity_ids:
        try:
            sources = list(es_col.where("entityId", "==", eid).limit(3).stream())
        except Exception:
            continue

        for s in sources:
            sd = s.to_dict()
            doc_id = sd.get("documentId", "")
            chunk_id = sd.get("chunkId", "")
            if chunk_id in seen:
                continue
            seen.add(chunk_id)

            doc_title = ""
            try:
                doc_snap = doc_col.document(doc_id).get()
                if doc_snap.exists:
                    doc_title = doc_snap.to_dict().get("title", "")
            except Exception:
                pass

            chunk_text = ""
            try:
                chunk_snap = chunk_col.document(chunk_id).get()
                if chunk_snap.exists:
                    chunk_text = chunk_snap.to_dict().get("text", "")[:300]
            except Exception:
                pass

            chunks.append({
                "chunk_id": chunk_id,
                "document_id": doc_id,
                "document_title": doc_title,
                "text": chunk_text,
                "score": 1.0,
            })

    return chunks[:10]


@router.post("/search/rebuild")
def rebuild_search_index(auth: AuthStore = Depends(get_auth_store)):
    """Rebuild search indexes. On Firestore, re-embeds entities without embeddings."""
    store = auth.store
    db_backend = os.environ.get("DB_BACKEND", "sqlite").lower()

    if db_backend == "firestore":
        from ..services.embedding import embed_texts
        from google.cloud.firestore_v1.vector import Vector

        entity_col = store._db.collection("workspaces").document(store._workspace_id).collection("entities")
        all_entities = list(entity_col.stream())
        to_embed = [(e.id, e.to_dict()["canonicalName"]) for e in all_entities if not e.to_dict().get("embedding")]

        if to_embed:
            names = [name for _, name in to_embed]
            vectors = embed_texts(names)
            for (eid, _), vec in zip(to_embed, vectors):
                entity_col.document(eid).update({"embedding": Vector(vec)})

        store.close()
        return {"status": "rebuilt", "new_entities_embedded": len(to_embed)}
    else:
        from ..pipeline.search import build_indexes, embed_new_entities, embed_new_chunks
        new_entities = embed_new_entities(store.conn)
        new_chunks = embed_new_chunks(store.conn)
        stats = build_indexes(store.conn)
        store.close()
        return {"status": "rebuilt", "new_entities_embedded": new_entities, "new_chunks_embedded": new_chunks, **stats}
