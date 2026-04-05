"""Three-tier entity normalization cascade.

Tier 1: String rules (lowercase, strip, plural collapse) — runs inline during extraction
Tier 2: Embedding similarity (Vertex AI text-embedding-004, cosine) — runs after batch extraction
Tier 3: LLM review for ambiguous clusters — manual trigger, reviews queued pairs

Validated from warhammer pipeline: 14,033 → 12,159 entities (13.4% reduction).
"""

import uuid
import sqlite3
import numpy as np
from collections import defaultdict


def embed_entities(names: list[str]) -> np.ndarray:
    """Embed a list of entity names. Returns (N, dim) array.

    Uses Vertex AI (768-dim) with sentence-transformers fallback (384-dim).
    """
    try:
        from ..services.embedding import embed_texts
        vectors = embed_texts(names)
        arr = np.array(vectors, dtype=np.float32)
        # Normalize for cosine similarity via dot product
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return arr / norms
    except Exception:
        pass

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model.encode(names, normalize_embeddings=True)
    except ImportError:
        return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two normalized vectors."""
    return float(np.dot(a, b))


# --- Tier 1: String rules ---

PLURAL_SUFFIXES = [
    ("ies", "y"),   # companies → company
    ("ses", "s"),   # processes → process
    ("es", "e"),    # techniques → technique
    ("s", ""),      # agents → agent
]

def normalize_string(name: str) -> str:
    """Lowercase, strip, basic cleanup."""
    return name.lower().strip().replace("  ", " ")


def collapse_plural(name: str, existing_names: set[str]) -> str | None:
    """If the singular form exists in the corpus, return it. Otherwise None."""
    for suffix, replacement in PLURAL_SUFFIXES:
        if name.endswith(suffix):
            singular = name[:-len(suffix)] + replacement
            if singular in existing_names and singular != name:
                return singular
    return None


AUTO_MERGE_THRESHOLD = 0.85
REVIEW_THRESHOLD = 0.70


def _is_store(obj):
    """Check if obj is a DataStore (has repository attributes)."""
    return hasattr(obj, 'entities') and hasattr(obj, 'normalization')


def _merge_entities_store(store, from_id, from_name, to_id, to_name, method, similarity):
    """Merge from_entity into to_entity using repository methods."""
    store.entity_sources.update_entity_id(from_id, to_id)
    store.relationships.update_entity_references(from_id, to_id)
    store.normalization.create_merge_map_entry(from_name, to_id)
    store.normalization.create_merge_log(str(uuid.uuid4()), from_id, from_name, to_id, to_name, method, similarity)
    store.entities.delete(from_id)


def _merge_entities_conn(conn, from_id, from_name, to_id, to_name, method, similarity):
    """Merge from_entity into to_entity using raw SQL."""
    conn.execute("UPDATE entity_sources SET entity_id = ? WHERE entity_id = ?", (to_id, from_id))
    conn.execute("UPDATE relationships SET from_entity = ? WHERE from_entity = ?", (to_id, from_id))
    conn.execute("UPDATE relationships SET to_entity = ? WHERE to_entity = ?", (to_id, from_id))
    conn.execute("INSERT OR REPLACE INTO merge_map (from_name, to_entity_id) VALUES (?, ?)", (from_name, to_id))
    conn.execute(
        "INSERT INTO normalization_log (id, from_entity_id, from_name, to_entity_id, to_name, method, similarity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), from_id, from_name, to_id, to_name, method, similarity))
    conn.execute("DELETE FROM entity_embeddings WHERE entity_id = ?", (from_id,))
    conn.execute("DELETE FROM entities WHERE id = ?", (from_id,))
    conn.commit()


def _merge_entities(store_or_conn, **kwargs):
    if _is_store(store_or_conn):
        _merge_entities_store(store_or_conn, **kwargs)
    else:
        _merge_entities_conn(store_or_conn, **kwargs)


def run_batch_normalization(store_or_conn) -> dict:
    """Run the full normalization cascade on all entities.

    Accepts either a DataStore or raw sqlite3.Connection.
    """
    results = {
        "plural_merges": 0, "embedding_merges": 0,
        "queued_for_review": 0, "total_entities_before": 0, "total_entities_after": 0,
    }

    if _is_store(store_or_conn):
        return _run_batch_store(store_or_conn, results)
    else:
        return _run_batch_conn(store_or_conn, results)


def _run_batch_store(store, results):
    """Batch normalization using repository methods."""
    entities = store.entities.get_all_for_normalization()
    results["total_entities_before"] = len(entities)

    if len(entities) < 2:
        results["total_entities_after"] = len(entities)
        return results

    # Tier 1: Plural collapse
    all_names = {e.canonical_name for e in entities}
    for e in entities:
        singular = collapse_plural(e.canonical_name, all_names)
        if singular:
            target = store.entities.get_by_name(singular, e.type)
            if target and target.id != e.id:
                _merge_entities_store(store, from_id=e.id, from_name=e.canonical_name,
                                      to_id=target.id, to_name=singular, method="plural", similarity=1.0)
                results["plural_merges"] += 1

    # Re-fetch after merges
    entities = store.entities.get_all_for_normalization()
    if len(entities) < 2:
        results["total_entities_after"] = len(entities)
        return results

    names = [e.canonical_name for e in entities]
    ids = [e.id for e in entities]
    types = [e.type for e in entities]

    # Tier 2: Embedding similarity
    embeddings = embed_entities(names)
    if embeddings is None:
        return results  # No embedding backend available — skip similarity matching

    # Store embeddings
    for i, eid in enumerate(ids):
        store.entities.update_embedding(eid, embeddings[i].tobytes())

    # Find similar pairs within same type
    type_groups = defaultdict(list)
    for i, t in enumerate(types):
        type_groups[t].append(i)

    merged_ids = set()
    for type_name, indices in type_groups.items():
        if len(indices) < 2:
            continue
        for i_idx in range(len(indices)):
            i = indices[i_idx]
            if ids[i] in merged_ids:
                continue
            for j_idx in range(i_idx + 1, len(indices)):
                j = indices[j_idx]
                if ids[j] in merged_ids:
                    continue

                sim = cosine_similarity(embeddings[i], embeddings[j])

                if sim >= AUTO_MERGE_THRESHOLD:
                    count_i = store.entity_sources.get_source_count(ids[i])
                    count_j = store.entity_sources.get_source_count(ids[j])
                    if count_i >= count_j:
                        _merge_entities_store(store, from_id=ids[j], from_name=names[j],
                                              to_id=ids[i], to_name=names[i], method="embedding", similarity=sim)
                        merged_ids.add(ids[j])
                    else:
                        _merge_entities_store(store, from_id=ids[i], from_name=names[i],
                                              to_id=ids[j], to_name=names[j], method="embedding", similarity=sim)
                        merged_ids.add(ids[i])
                    results["embedding_merges"] += 1

                elif sim >= REVIEW_THRESHOLD:
                    existing = store.normalization.get_existing_review(ids[i], ids[j])
                    if not existing:
                        store.normalization.create_review(
                            str(uuid.uuid4()), ids[i], names[i], ids[j], names[j], sim)
                        results["queued_for_review"] += 1

    results["total_entities_after"] = store.entities.count()
    return results


def _run_batch_conn(conn, results):
    """Batch normalization using raw SQL (legacy)."""
    entities = conn.execute("SELECT id, canonical_name, type FROM entities ORDER BY canonical_name").fetchall()
    results["total_entities_before"] = len(entities)

    if len(entities) < 2:
        results["total_entities_after"] = len(entities)
        return results

    # Tier 1
    all_names = {e[1] for e in entities}
    for entity in entities:
        eid, name, etype = entity[0], entity[1], entity[2]
        singular = collapse_plural(name, all_names)
        if singular:
            target = conn.execute("SELECT id FROM entities WHERE canonical_name = ? AND type = ?", (singular, etype)).fetchone()
            if target and target[0] != eid:
                _merge_entities_conn(conn, from_id=eid, from_name=name,
                                     to_id=target[0], to_name=singular, method="plural", similarity=1.0)
                results["plural_merges"] += 1

    # Tier 2
    entities = conn.execute("SELECT id, canonical_name, type FROM entities ORDER BY canonical_name").fetchall()
    if len(entities) < 2:
        results["total_entities_after"] = len(entities)
        return results

    names = [e[1] for e in entities]
    ids = [e[0] for e in entities]
    types = [e[2] for e in entities]

    embeddings = embed_entities(names)
    if embeddings is None:
        return results  # No embedding backend available — skip similarity matching

    for i, eid in enumerate(ids):
        conn.execute("INSERT OR REPLACE INTO entity_embeddings (entity_id, embedding) VALUES (?, ?)",
                      (eid, embeddings[i].tobytes()))
    conn.commit()

    type_groups = defaultdict(list)
    for i, t in enumerate(types):
        type_groups[t].append(i)

    merged_ids = set()
    for type_name, indices in type_groups.items():
        if len(indices) < 2:
            continue
        for i_idx in range(len(indices)):
            i = indices[i_idx]
            if ids[i] in merged_ids:
                continue
            for j_idx in range(i_idx + 1, len(indices)):
                j = indices[j_idx]
                if ids[j] in merged_ids:
                    continue

                sim = cosine_similarity(embeddings[i], embeddings[j])
                if sim >= AUTO_MERGE_THRESHOLD:
                    count_i = conn.execute("SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (ids[i],)).fetchone()[0]
                    count_j = conn.execute("SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (ids[j],)).fetchone()[0]
                    if count_i >= count_j:
                        _merge_entities_conn(conn, from_id=ids[j], from_name=names[j],
                                             to_id=ids[i], to_name=names[i], method="embedding", similarity=sim)
                        merged_ids.add(ids[j])
                    else:
                        _merge_entities_conn(conn, from_id=ids[i], from_name=names[i],
                                             to_id=ids[j], to_name=names[j], method="embedding", similarity=sim)
                        merged_ids.add(ids[i])
                    results["embedding_merges"] += 1

                elif sim >= REVIEW_THRESHOLD:
                    existing = conn.execute(
                        "SELECT id FROM normalization_review_queue WHERE "
                        "((entity_a_id = ? AND entity_b_id = ?) OR (entity_a_id = ? AND entity_b_id = ?))",
                        (ids[i], ids[j], ids[j], ids[i])).fetchone()
                    if not existing:
                        conn.execute(
                            "INSERT INTO normalization_review_queue (id, entity_a_id, entity_a_name, entity_b_id, entity_b_name, similarity) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (str(uuid.uuid4()), ids[i], names[i], ids[j], names[j], sim))
                        results["queued_for_review"] += 1

    conn.commit()
    results["total_entities_after"] = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    return results


def get_normalization_summary(store_or_conn) -> dict:
    if _is_store(store_or_conn):
        return store_or_conn.normalization.get_merge_summary()
    conn = store_or_conn
    merges = conn.execute("SELECT method, COUNT(*) FROM normalization_log GROUP BY method").fetchall()
    recent = conn.execute(
        "SELECT from_name, to_name, method, similarity, created_at "
        "FROM normalization_log ORDER BY created_at DESC LIMIT 20").fetchall()
    pending = conn.execute("SELECT COUNT(*) FROM normalization_review_queue WHERE status = 'pending'").fetchone()[0]
    return {
        "merges_by_method": {r[0]: r[1] for r in merges},
        "total_merges": sum(r[1] for r in merges),
        "pending_reviews": pending,
        "recent_merges": [{"from": r[0], "to": r[1], "method": r[2], "similarity": round(r[3], 3), "date": r[4]} for r in recent],
    }


def get_review_queue(store_or_conn) -> list[dict]:
    if _is_store(store_or_conn):
        reviews = store_or_conn.normalization.get_review_queue()
        return [{"id": r.id, "entity_a": r.entity_a_name, "entity_b": r.entity_b_name,
                 "similarity": round(r.similarity, 3)} for r in reviews]
    conn = store_or_conn
    rows = conn.execute(
        "SELECT id, entity_a_name, entity_b_name, similarity "
        "FROM normalization_review_queue WHERE status = 'pending' ORDER BY similarity DESC").fetchall()
    return [{"id": r[0], "entity_a": r[1], "entity_b": r[2], "similarity": round(r[3], 3)} for r in rows]


def resolve_review(store_or_conn, review_id: str, action: str) -> None:
    if _is_store(store_or_conn):
        store = store_or_conn
        if action == "merge":
            review = store.normalization.get_review_by_id(review_id)
            if review:
                count_a = store.entity_sources.get_source_count(review.entity_a_id)
                count_b = store.entity_sources.get_source_count(review.entity_b_id)
                if count_a >= count_b:
                    _merge_entities_store(store, from_id=review.entity_b_id, from_name=review.entity_b_name,
                                          to_id=review.entity_a_id, to_name=review.entity_a_name,
                                          method="llm_review", similarity=review.similarity)
                else:
                    _merge_entities_store(store, from_id=review.entity_a_id, from_name=review.entity_a_name,
                                          to_id=review.entity_b_id, to_name=review.entity_b_name,
                                          method="llm_review", similarity=review.similarity)
        store.normalization.resolve_review(review_id, action)
        return

    conn = store_or_conn
    review = conn.execute(
        "SELECT entity_a_id, entity_a_name, entity_b_id, entity_b_name, similarity "
        "FROM normalization_review_queue WHERE id = ?", (review_id,)).fetchone()
    if not review:
        return

    if action == "merge":
        count_a = conn.execute("SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (review[0],)).fetchone()[0]
        count_b = conn.execute("SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (review[2],)).fetchone()[0]
        if count_a >= count_b:
            _merge_entities_conn(conn, from_id=review[2], from_name=review[3],
                                 to_id=review[0], to_name=review[1], method="llm_review", similarity=review[4])
        else:
            _merge_entities_conn(conn, from_id=review[0], from_name=review[1],
                                 to_id=review[2], to_name=review[3], method="llm_review", similarity=review[4])

    conn.execute("UPDATE normalization_review_queue SET status = 'resolved', resolution = ? WHERE id = ?", (action, review_id))
    conn.commit()
