"""Stage 1: Parallel retrieval — FAISS semantic + exact match."""

import sqlite3
import threading
import numpy as np
from .models import ScoredEntity, ScoredChunk
from .config import SearchConfig

# Lazy-loaded model + indexes
_model = None
_entity_index = None
_chunk_index = None
_entity_ids: list[str] = []
_chunk_ids: list[str] = []

# torch (sentence-transformers) and faiss each bring their own native
# threading/OpenMP runtime. Invoking them concurrently from multiple requests
# in the same process (e.g. a search request racing an ingest's inline
# embedding step) can crash the process natively (SIGBUS/SIGILL) — the
# concurrent-hit failure mode already noted in docker-compose.yml. Serialize
# all model/FAISS access process-wide so two calls never execute at once.
_native_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_text(text: str | list[str]) -> np.ndarray:
    """Embed text(s) with all-MiniLM-L6-v2."""
    with _native_lock:
        model = _get_model()
        if isinstance(text, str):
            text = [text]
        return model.encode(text, normalize_embeddings=True).astype(np.float32)


def build_indexes(conn: sqlite3.Connection) -> dict:
    """Build FAISS indexes from stored embeddings, or embed if missing. SQLite only."""
    import faiss
    global _entity_index, _chunk_index, _entity_ids, _chunk_ids

    with _native_lock:
        return _build_indexes_locked(conn, faiss)


def _build_indexes_locked(conn: sqlite3.Connection, faiss) -> dict:
    global _entity_index, _chunk_index, _entity_ids, _chunk_ids

    model = _get_model()

    # Entity index
    entities = conn.execute("SELECT id, canonical_name, embedding FROM entities ORDER BY canonical_name").fetchall()
    if entities:
        _entity_ids = [e[0] for e in entities]
        # Use stored embeddings if available, otherwise compute
        embeddings = []
        needs_embed = []
        for i, e in enumerate(entities):
            if e[2]:
                embeddings.append(np.frombuffer(e[2], dtype=np.float32))
            else:
                needs_embed.append((i, e[1]))
                embeddings.append(None)

        if needs_embed:
            names = [n for _, n in needs_embed]
            new_embeds = model.encode(names, normalize_embeddings=True).astype(np.float32)
            for j, (idx, _) in enumerate(needs_embed):
                embeddings[idx] = new_embeds[j]
                # Store back to DB
                conn.execute("UPDATE entities SET embedding = ? WHERE id = ?",
                             (new_embeds[j].tobytes(), entities[idx][0]))
            conn.commit()

        entity_matrix = np.stack([e for e in embeddings if e is not None])
        _entity_index = faiss.IndexFlatIP(entity_matrix.shape[1])
        _entity_index.add(entity_matrix)
    else:
        _entity_index = None
        _entity_ids = []

    # Chunk index
    chunks = conn.execute("SELECT id, text, embedding FROM chunks ORDER BY id").fetchall()
    if chunks:
        _chunk_ids = [c[0] for c in chunks]
        embeddings = []
        needs_embed = []
        for i, c in enumerate(chunks):
            if c[2]:
                embeddings.append(np.frombuffer(c[2], dtype=np.float32))
            else:
                needs_embed.append((i, c[1][:512]))
                embeddings.append(None)

        if needs_embed:
            texts = [t for _, t in needs_embed]
            new_embeds = model.encode(texts, normalize_embeddings=True, batch_size=64).astype(np.float32)
            for j, (idx, _) in enumerate(needs_embed):
                embeddings[idx] = new_embeds[j]
                conn.execute("UPDATE chunks SET embedding = ? WHERE id = ?",
                             (new_embeds[j].tobytes(), chunks[idx][0]))
            conn.commit()

        chunk_matrix = np.stack([e for e in embeddings if e is not None])
        _chunk_index = faiss.IndexFlatIP(chunk_matrix.shape[1])
        _chunk_index.add(chunk_matrix)
    else:
        _chunk_index = None
        _chunk_ids = []

    return {"entities": len(_entity_ids), "chunks": len(_chunk_ids)}


def embed_new_entities(conn: sqlite3.Connection):
    """Embed entities that don't have embeddings yet."""
    with _native_lock:
        model = _get_model()
        rows = conn.execute("SELECT id, canonical_name FROM entities WHERE embedding IS NULL").fetchall()
        if not rows:
            return 0
        names = [r[1] for r in rows]
        embeds = model.encode(names, normalize_embeddings=True).astype(np.float32)
        for i, row in enumerate(rows):
            conn.execute("UPDATE entities SET embedding = ? WHERE id = ?", (embeds[i].tobytes(), row[0]))
        conn.commit()
        return len(rows)


def embed_new_chunks(conn: sqlite3.Connection):
    """Embed chunks that don't have embeddings yet."""
    with _native_lock:
        model = _get_model()
        rows = conn.execute("SELECT id, text FROM chunks WHERE embedding IS NULL").fetchall()
        if not rows:
            return 0
        texts = [r[1][:512] for r in rows]
        embeds = model.encode(texts, normalize_embeddings=True, batch_size=64).astype(np.float32)
        for i, row in enumerate(rows):
            conn.execute("UPDATE chunks SET embedding = ? WHERE id = ?", (embeds[i].tobytes(), row[0]))
        conn.commit()
        return len(rows)


def search_entities_semantic(query_embedding: np.ndarray, top_k: int = 20) -> list[ScoredEntity]:
    """Channel A: FAISS entity search."""
    if _entity_index is None or _entity_index.ntotal == 0:
        return []
    k = min(top_k, _entity_index.ntotal)
    with _native_lock:
        scores, indices = _entity_index.search(query_embedding.reshape(1, -1), k)
    results = []
    for rank, (score, idx) in enumerate(zip(scores[0], indices[0])):
        if idx < 0 or idx >= len(_entity_ids):
            continue
        results.append(ScoredEntity(
            entity_id=_entity_ids[idx], name="", entity_type="",
            score=float(score), rank=rank, source="semantic",
        ))
    return results


def search_chunks_semantic(query_embedding: np.ndarray, top_k: int = 20) -> list[ScoredChunk]:
    """Channel B: FAISS chunk search."""
    if _chunk_index is None or _chunk_index.ntotal == 0:
        return []
    k = min(top_k, _chunk_index.ntotal)
    with _native_lock:
        scores, indices = _chunk_index.search(query_embedding.reshape(1, -1), k)
    results = []
    for rank, (score, idx) in enumerate(zip(scores[0], indices[0])):
        if idx < 0 or idx >= len(_chunk_ids):
            continue
        results.append(ScoredChunk(
            chunk_id=_chunk_ids[idx], text="", document_id="", document_title="",
            score=float(score), rank=rank, source="semantic",
        ))
    return results


def search_entities_exact(conn: sqlite3.Connection, query: str, min_term_length: int = 3) -> list[ScoredEntity]:
    """Channel C: Exact/substring match on entity names."""
    query_lower = query.lower().strip()
    results = []
    seen = set()

    # Exact full match
    rows = conn.execute(
        "SELECT id, canonical_name, type FROM entities WHERE LOWER(canonical_name) = ?",
        (query_lower,)
    ).fetchall()
    for r in rows:
        seen.add(r[0])
        source_count = conn.execute("SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (r[0],)).fetchone()[0]
        results.append(ScoredEntity(
            entity_id=r[0], name=r[1], entity_type=r[2],
            score=1.0, rank=0, source="exact", source_count=source_count,
        ))

    # Substring match per term
    for term in query_lower.split():
        if len(term) < min_term_length:
            continue
        rows = conn.execute(
            "SELECT id, canonical_name, type FROM entities WHERE LOWER(canonical_name) LIKE ? AND id NOT IN ({})".format(
                ",".join("?" * len(seen)) if seen else "''"
            ),
            (f"%{term}%", *list(seen))
        ).fetchall()
        for r in rows:
            if r[0] in seen:
                continue
            seen.add(r[0])
            source_count = conn.execute("SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (r[0],)).fetchone()[0]
            results.append(ScoredEntity(
                entity_id=r[0], name=r[1], entity_type=r[2],
                score=0.7, rank=len(results), source="exact", source_count=source_count,
            ))

    return results
