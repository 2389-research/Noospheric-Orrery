# ABOUTME: Embedding-rebuild job — moves entity/chunk embedding out of the ingest request path.
# ABOUTME: Runs in the worker process so it never races the orchestrator's own model/FAISS calls.

from ..db import get_connection


async def run_embed_index(job: dict, db_path: str) -> None:
    """Embed any entities/chunks still missing embeddings for this workspace.

    Idempotent — safe to run repeatedly; only touches rows with embedding IS NULL.
    Runs in the worker's own process/address space so it can't collide with the
    orchestrator's sentence-transformers/FAISS calls (the source of the SIGBUS
    crashes seen when this ran inline during ingest under concurrent request load).
    """
    conn = get_connection(db_path)
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np

        model = SentenceTransformer("all-MiniLM-L6-v2")

        entity_rows = conn.execute("SELECT id, canonical_name FROM entities WHERE embedding IS NULL").fetchall()
        if entity_rows:
            names = [r[1] for r in entity_rows]
            embeds = model.encode(names, normalize_embeddings=True).astype(np.float32)
            for i, row in enumerate(entity_rows):
                conn.execute("UPDATE entities SET embedding = ? WHERE id = ?", (embeds[i].tobytes(), row[0]))
            conn.commit()

        chunk_rows = conn.execute("SELECT id, text FROM chunks WHERE embedding IS NULL").fetchall()
        if chunk_rows:
            texts = [r[1][:512] for r in chunk_rows]
            embeds = model.encode(texts, normalize_embeddings=True, batch_size=64).astype(np.float32)
            for i, row in enumerate(chunk_rows):
                conn.execute("UPDATE chunks SET embedding = ? WHERE id = ?", (embeds[i].tobytes(), row[0]))
            conn.commit()
    finally:
        conn.close()
