"""Stage 1: Parallel retrieval — FAISS semantic + exact match."""

# Every read of `entities` outside search already applies `invalid_at IS NULL`
# (graph_ops, the repositories); search was the one surface that did not, so an entity
# removed through the corrections flow still surfaced here while every other view
# correctly hid it. Written out literally at each site, as the rest of the codebase
# does — a constant would force these into f-strings for no gain.

import sqlite3
import numpy as np
from .models import ScoredEntity, ScoredChunk
from .config import SearchConfig

# Lazy-loaded model + indexes.
#
# An index and its id list are ONE value, published as a tuple, because they are only
# meaningful together: a FAISS position means nothing except as an offset into the id
# list built alongside it. Held as two globals they could be swapped independently, so a
# search running during a rebuild could take positions from one build and ids from
# another and return entities that were never the match — wrong answers, silently.
#
# Rebinding a name is a single bytecode, so a reader that grabs the tuple ONCE sees
# either the whole old pair or the whole new one, never a mix. That is the entire
# protocol: writers assign the tuple last, readers bind it to a local first.
_model = None
_entity_view: tuple = (None, [])   # (faiss index | None, ids)
_chunk_view: tuple = (None, [])


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_text(text: str | list[str]) -> np.ndarray:
    """Embed text(s) with all-MiniLM-L6-v2."""
    model = _get_model()
    if isinstance(text, str):
        text = [text]
    return model.encode(text, normalize_embeddings=True).astype(np.float32)


def build_indexes(conn: sqlite3.Connection) -> dict:
    """Build FAISS indexes from stored embeddings, or embed if missing. SQLite only."""
    import faiss
    global _entity_view, _chunk_view

    # NOT `model = _get_model()` up front. That instantiates (and, on a cold host,
    # DOWNLOADS) all-MiniLM-L6-v2 on every index build — including the common case
    # where every row already has a stored embedding and nothing needs encoding.
    # Resolved instead at the two points that actually encode.

    # Entity index
    # Build-time filter: a soft-deleted entity must never enter the index at all.
    entities = conn.execute(
        "SELECT id, canonical_name, embedding FROM entities "
        "WHERE invalid_at IS NULL ORDER BY canonical_name").fetchall()
    if entities:
        entity_ids = [e[0] for e in entities]
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
            new_embeds = _get_model().encode(names, normalize_embeddings=True).astype(np.float32)
            for j, (idx, _) in enumerate(needs_embed):
                embeddings[idx] = new_embeds[j]
                # Store back to DB
                conn.execute("UPDATE entities SET embedding = ? WHERE id = ?",
                             (new_embeds[j].tobytes(), entities[idx][0]))
            conn.commit()

        entity_matrix = np.stack([e for e in embeddings if e is not None])
        entity_index = faiss.IndexFlatIP(entity_matrix.shape[1])
        entity_index.add(entity_matrix)
    else:
        entity_index, entity_ids = None, []
    # Published as one value, AFTER it is fully built — see `_entity_view`.
    _entity_view = (entity_index, entity_ids)

    # Chunk index
    chunks = conn.execute("SELECT c.id, c.text, c.embedding FROM chunks c JOIN documents d ON c.document_id = d.id WHERE d.invalid_at IS NULL ORDER BY c.id").fetchall()
    if chunks:
        chunk_ids = [c[0] for c in chunks]
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
            new_embeds = _get_model().encode(
                texts, normalize_embeddings=True, batch_size=64).astype(np.float32)
            for j, (idx, _) in enumerate(needs_embed):
                embeddings[idx] = new_embeds[j]
                conn.execute("UPDATE chunks SET embedding = ? WHERE id = ?",
                             (new_embeds[j].tobytes(), chunks[idx][0]))
            conn.commit()

        chunk_matrix = np.stack([e for e in embeddings if e is not None])
        chunk_index = faiss.IndexFlatIP(chunk_matrix.shape[1])
        chunk_index.add(chunk_matrix)
    else:
        chunk_index, chunk_ids = None, []
    _chunk_view = (chunk_index, chunk_ids)

    return {"entities": len(entity_ids), "chunks": len(chunk_ids)}


def embed_new_entities(conn: sqlite3.Connection):
    """Embed entities that don't have embeddings yet."""
    model = _get_model()
    rows = conn.execute(
        "SELECT id, canonical_name FROM entities "
        "WHERE embedding IS NULL AND invalid_at IS NULL").fetchall()
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
    # Bind the pair ONCE: a rebuild between these statements would otherwise pair this
    # index's positions with the next build's ids.
    index, ids = _entity_view
    if index is None or index.ntotal == 0:
        return []
    k = min(top_k, index.ntotal)
    scores, indices = index.search(query_embedding.reshape(1, -1), k)
    results = []
    for rank, (score, idx) in enumerate(zip(scores[0], indices[0], strict=True)):
        if idx < 0 or idx >= len(ids):
            continue
        results.append(ScoredEntity(
            entity_id=ids[idx], name="", entity_type="",
            score=float(score), rank=rank, source="semantic",
        ))
    return results


def search_chunks_semantic(query_embedding: np.ndarray, top_k: int = 20) -> list[ScoredChunk]:
    """Channel B: FAISS chunk search."""
    index, ids = _chunk_view
    if index is None or index.ntotal == 0:
        return []
    k = min(top_k, index.ntotal)
    scores, indices = index.search(query_embedding.reshape(1, -1), k)
    results = []
    for rank, (score, idx) in enumerate(zip(scores[0], indices[0], strict=True)):
        if idx < 0 or idx >= len(ids):
            continue
        results.append(ScoredChunk(
            chunk_id=ids[idx], text="", document_id="", document_title="",
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
        "SELECT id, canonical_name, type FROM entities "
        "WHERE LOWER(canonical_name) = ? AND invalid_at IS NULL",
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
        # No SQL-level `id NOT IN (...)`: the `seen` check below already skips
        # duplicates, so that clause bought nothing and was the only reason this
        # query had to be assembled at runtime.
        rows = conn.execute(
            "SELECT id, canonical_name, type FROM entities "
            "WHERE LOWER(canonical_name) LIKE ? AND invalid_at IS NULL",
            (f"%{term}%",)
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
