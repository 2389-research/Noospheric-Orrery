"""Search engine — FAISS semantic search + co-occurrence graph expansion + RRF fusion.

Three retrieval paths:
1. Entity search — FAISS over entity names (all-MiniLM-L6-v2)
2. Chunk search — FAISS over document chunks
3. Graph expansion — co-occurrence edges from top entity hits

Results fused via Reciprocal Rank Fusion (RRF).
"""

import sqlite3
import numpy as np
from collections import defaultdict

# Lazy-load heavy deps
_model = None
_entity_index = None
_chunk_index = None
_entity_ids = None
_chunk_ids = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def build_indexes(conn: sqlite3.Connection):
    """Build FAISS indexes from current DB state. Call on startup or after extraction."""
    global _entity_index, _chunk_index, _entity_ids, _chunk_ids
    import faiss

    model = _get_model()

    # Entity index
    entities = conn.execute("SELECT id, canonical_name FROM entities ORDER BY canonical_name").fetchall()
    if entities:
        entity_names = [e[1] for e in entities]
        _entity_ids = [e[0] for e in entities]
        entity_embeddings = model.encode(entity_names, normalize_embeddings=True)
        _entity_index = faiss.IndexFlatIP(entity_embeddings.shape[1])
        _entity_index.add(entity_embeddings.astype(np.float32))
    else:
        _entity_index = None
        _entity_ids = []

    # Chunk index
    chunks = conn.execute("SELECT id, text FROM chunks ORDER BY id").fetchall()
    if chunks:
        chunk_texts = [c[1][:512] for c in chunks]  # truncate long chunks for embedding
        _chunk_ids = [c[0] for c in chunks]
        chunk_embeddings = model.encode(chunk_texts, normalize_embeddings=True, batch_size=64)
        _chunk_index = faiss.IndexFlatIP(chunk_embeddings.shape[1])
        _chunk_index.add(chunk_embeddings.astype(np.float32))
    else:
        _chunk_index = None
        _chunk_ids = []

    return {"entities": len(_entity_ids or []), "chunks": len(_chunk_ids or [])}


def search(conn: sqlite3.Connection, query: str, top_k: int = 20) -> dict:
    """Run hybrid search. Returns entities, chunks, and graph context."""
    global _entity_index, _chunk_index, _entity_ids, _chunk_ids

    if _entity_index is None:
        build_indexes(conn)

    model = _get_model()
    query_embedding = model.encode([query], normalize_embeddings=True).astype(np.float32)

    entity_results = []
    chunk_results = []
    graph_results = []

    # Path 1: Entity search
    if _entity_index is not None and _entity_index.ntotal > 0:
        k = min(top_k, _entity_index.ntotal)
        scores, indices = _entity_index.search(query_embedding, k)
        for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
            if idx < 0 or idx >= len(_entity_ids):
                continue
            entity_id = _entity_ids[idx]
            entity = conn.execute(
                "SELECT canonical_name, type FROM entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if entity:
                source_count = conn.execute(
                    "SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (entity_id,)
                ).fetchone()[0]
                entity_results.append({
                    "id": entity_id,
                    "name": entity[0],
                    "type": entity[1],
                    "score": float(score),
                    "source_count": source_count,
                    "rank": i + 1,
                    "path": "entity",
                })

    # Path 2: Chunk search
    if _chunk_index is not None and _chunk_index.ntotal > 0:
        k = min(top_k, _chunk_index.ntotal)
        scores, indices = _chunk_index.search(query_embedding, k)
        for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
            if idx < 0 or idx >= len(_chunk_ids):
                continue
            chunk_id = _chunk_ids[idx]
            chunk = conn.execute(
                "SELECT document_id, text FROM chunks WHERE id = ?", (chunk_id,)
            ).fetchone()
            if chunk:
                doc = conn.execute(
                    "SELECT title FROM documents WHERE id = ?", (chunk[0],)
                ).fetchone()
                chunk_results.append({
                    "chunk_id": chunk_id,
                    "document_id": chunk[0],
                    "document_title": doc[0] if doc else "",
                    "text": chunk[1][:300],
                    "score": float(score),
                    "rank": i + 1,
                    "path": "chunk",
                })

    # Path 3: Graph expansion from top entity hits
    if entity_results:
        seed_ids = [e["id"] for e in entity_results[:5]]
        seen = set(e["id"] for e in entity_results)
        for seed_id in seed_ids:
            neighbors = conn.execute("""
                SELECT CASE WHEN from_entity = ? THEN to_entity ELSE from_entity END as neighbor_id,
                       weight
                FROM relationships
                WHERE (from_entity = ? OR to_entity = ?) AND type = 'co_occurs'
                ORDER BY weight DESC LIMIT 10
            """, (seed_id, seed_id, seed_id)).fetchall()

            for neighbor_id, weight in neighbors:
                if neighbor_id in seen:
                    continue
                seen.add(neighbor_id)
                entity = conn.execute(
                    "SELECT canonical_name, type FROM entities WHERE id = ?", (neighbor_id,)
                ).fetchone()
                if entity:
                    source_count = conn.execute(
                        "SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (neighbor_id,)
                    ).fetchone()[0]
                    graph_results.append({
                        "id": neighbor_id,
                        "name": entity[0],
                        "type": entity[1],
                        "score": float(weight) / 100,  # normalize weight to 0-1ish
                        "source_count": source_count,
                        "rank": len(graph_results) + 1,
                        "path": "graph",
                    })

    # RRF Fusion — merge entity results from all paths
    K = 60  # RRF constant
    entity_scores: dict[str, float] = defaultdict(float)
    entity_data: dict[str, dict] = {}

    for result_list in [entity_results, graph_results]:
        for r in result_list:
            eid = r["id"]
            entity_scores[eid] += 1.0 / (K + r["rank"])
            if eid not in entity_data:
                entity_data[eid] = r

    # Sort by fused score
    fused_entities = []
    for eid, fused_score in sorted(entity_scores.items(), key=lambda x: -x[1]):
        data = entity_data[eid]
        fused_entities.append({
            "id": data["id"],
            "name": data["name"],
            "type": data["type"],
            "source_count": data["source_count"],
            "score": round(fused_score, 4),
            "paths": list(set(
                r["path"] for rl in [entity_results, graph_results] for r in rl if r["id"] == eid
            )),
        })

    return {
        "query": query,
        "entities": fused_entities[:top_k],
        "chunks": chunk_results[:top_k],
        "total_entities": len(fused_entities),
        "total_chunks": len(chunk_results),
    }
