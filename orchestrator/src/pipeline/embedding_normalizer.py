"""Three-tier entity normalization cascade.

Tier 1: String rules (lowercase, strip, plural collapse) — runs inline during extraction
Tier 2: Embedding similarity (all-MiniLM-L6-v2, cosine) — runs after batch extraction
Tier 3: LLM review for ambiguous clusters — manual trigger, reviews queued pairs

Validated from warhammer pipeline: 14,033 → 12,159 entities (13.4% reduction).
"""

import uuid
import sqlite3
import numpy as np
from collections import defaultdict

# Lazy-load the model (heavy import)
_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_entities(names: list[str]) -> np.ndarray:
    """Embed a list of entity names. Returns (N, 384) array."""
    model = _get_model()
    return model.encode(names, normalize_embeddings=True)


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


# --- Tier 2: Embedding similarity ---

AUTO_MERGE_THRESHOLD = 0.85    # Above this: auto-merge
REVIEW_THRESHOLD = 0.70        # Between 0.70-0.85: queue for LLM review
# Below 0.70: definitely different


def run_batch_normalization(conn: sqlite3.Connection) -> dict:
    """Run the full normalization cascade on all entities.

    Returns summary of what was done.
    """
    results = {
        "plural_merges": 0,
        "embedding_merges": 0,
        "queued_for_review": 0,
        "total_entities_before": 0,
        "total_entities_after": 0,
    }

    # Get all entities
    entities = conn.execute(
        "SELECT id, canonical_name, type FROM entities ORDER BY canonical_name"
    ).fetchall()
    results["total_entities_before"] = len(entities)

    if len(entities) < 2:
        results["total_entities_after"] = len(entities)
        return results

    # --- Tier 1: Plural collapse ---
    all_names = {e[1] for e in entities}
    for entity in entities:
        eid, name, etype = entity[0], entity[1], entity[2]
        singular = collapse_plural(name, all_names)
        if singular:
            # Find the entity with the singular name
            target = conn.execute(
                "SELECT id FROM entities WHERE canonical_name = ? AND type = ?",
                (singular, etype)
            ).fetchone()
            if target and target[0] != eid:
                _merge_entities(conn, from_id=eid, from_name=name,
                               to_id=target[0], to_name=singular, method="plural", similarity=1.0)
                results["plural_merges"] += 1

    # --- Tier 2: Embedding similarity ---
    # Re-fetch entities (some may have been merged)
    entities = conn.execute(
        "SELECT id, canonical_name, type FROM entities ORDER BY canonical_name"
    ).fetchall()

    if len(entities) < 2:
        results["total_entities_after"] = len(entities)
        return results

    names = [e[1] for e in entities]
    ids = [e[0] for e in entities]
    types = [e[2] for e in entities]

    # Embed all entities
    embeddings = embed_entities(names)

    # Store embeddings
    for i, eid in enumerate(ids):
        conn.execute(
            "INSERT OR REPLACE INTO entity_embeddings (entity_id, embedding) VALUES (?, ?)",
            (eid, embeddings[i].tobytes())
        )
    conn.commit()

    # Find similar pairs (only compare within same type)
    type_groups: dict[str, list[int]] = defaultdict(list)
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
                    # Auto-merge: keep the one with more sources (= more common)
                    count_i = conn.execute(
                        "SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (ids[i],)
                    ).fetchone()[0]
                    count_j = conn.execute(
                        "SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (ids[j],)
                    ).fetchone()[0]

                    if count_i >= count_j:
                        _merge_entities(conn, from_id=ids[j], from_name=names[j],
                                       to_id=ids[i], to_name=names[i],
                                       method="embedding", similarity=sim)
                        merged_ids.add(ids[j])
                    else:
                        _merge_entities(conn, from_id=ids[i], from_name=names[i],
                                       to_id=ids[j], to_name=names[j],
                                       method="embedding", similarity=sim)
                        merged_ids.add(ids[i])
                    results["embedding_merges"] += 1

                elif sim >= REVIEW_THRESHOLD:
                    # Queue for LLM review — skip if already reviewed (any status)
                    existing = conn.execute(
                        "SELECT id FROM normalization_review_queue WHERE "
                        "((entity_a_id = ? AND entity_b_id = ?) OR (entity_a_id = ? AND entity_b_id = ?))",
                        (ids[i], ids[j], ids[j], ids[i])
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            "INSERT INTO normalization_review_queue (id, entity_a_id, entity_a_name, entity_b_id, entity_b_name, similarity) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (str(uuid.uuid4()), ids[i], names[i], ids[j], names[j], sim)
                        )
                        results["queued_for_review"] += 1

    conn.commit()

    # Count remaining entities
    remaining = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    results["total_entities_after"] = remaining

    return results


def _merge_entities(
    conn: sqlite3.Connection,
    from_id: str, from_name: str,
    to_id: str, to_name: str,
    method: str, similarity: float,
) -> None:
    """Merge from_entity into to_entity. Updates all references."""
    # Move entity_sources to target
    conn.execute(
        "UPDATE entity_sources SET entity_id = ? WHERE entity_id = ?",
        (to_id, from_id)
    )
    # Move relationship references
    conn.execute(
        "UPDATE relationships SET from_entity = ? WHERE from_entity = ?",
        (to_id, from_id)
    )
    conn.execute(
        "UPDATE relationships SET to_entity = ? WHERE to_entity = ?",
        (to_id, from_id)
    )
    # Add to merge map
    conn.execute(
        "INSERT OR REPLACE INTO merge_map (from_name, to_entity_id) VALUES (?, ?)",
        (from_name, to_id)
    )
    # Log the merge
    conn.execute(
        "INSERT INTO normalization_log (id, from_entity_id, from_name, to_entity_id, to_name, method, similarity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), from_id, from_name, to_id, to_name, method, similarity)
    )
    # Delete the merged entity
    conn.execute("DELETE FROM entity_embeddings WHERE entity_id = ?", (from_id,))
    conn.execute("DELETE FROM entities WHERE id = ?", (from_id,))
    conn.commit()


def get_normalization_summary(conn: sqlite3.Connection) -> dict:
    """Get summary of all normalization activity."""
    merges = conn.execute(
        "SELECT method, COUNT(*) FROM normalization_log GROUP BY method"
    ).fetchall()

    recent = conn.execute(
        "SELECT from_name, to_name, method, similarity, created_at "
        "FROM normalization_log ORDER BY created_at DESC LIMIT 20"
    ).fetchall()

    pending_reviews = conn.execute(
        "SELECT COUNT(*) FROM normalization_review_queue WHERE status = 'pending'"
    ).fetchone()[0]

    return {
        "merges_by_method": {r[0]: r[1] for r in merges},
        "total_merges": sum(r[1] for r in merges),
        "pending_reviews": pending_reviews,
        "recent_merges": [
            {"from": r[0], "to": r[1], "method": r[2], "similarity": round(r[3], 3), "date": r[4]}
            for r in recent
        ],
    }


def get_review_queue(conn: sqlite3.Connection) -> list[dict]:
    """Get pending normalization reviews."""
    rows = conn.execute(
        "SELECT id, entity_a_name, entity_b_name, similarity "
        "FROM normalization_review_queue WHERE status = 'pending' "
        "ORDER BY similarity DESC"
    ).fetchall()
    return [
        {"id": r[0], "entity_a": r[1], "entity_b": r[2], "similarity": round(r[3], 3)}
        for r in rows
    ]


def resolve_review(conn: sqlite3.Connection, review_id: str, action: str) -> None:
    """Resolve a review queue item. action = 'merge' or 'keep_separate'."""
    review = conn.execute(
        "SELECT entity_a_id, entity_a_name, entity_b_id, entity_b_name, similarity "
        "FROM normalization_review_queue WHERE id = ?",
        (review_id,)
    ).fetchone()
    if not review:
        return

    if action == "merge":
        # Merge b into a (a is kept as canonical)
        count_a = conn.execute(
            "SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (review[0],)
        ).fetchone()[0]
        count_b = conn.execute(
            "SELECT COUNT(*) FROM entity_sources WHERE entity_id = ?", (review[2],)
        ).fetchone()[0]

        if count_a >= count_b:
            _merge_entities(conn, from_id=review[2], from_name=review[3],
                           to_id=review[0], to_name=review[1],
                           method="llm_review", similarity=review[4])
        else:
            _merge_entities(conn, from_id=review[0], from_name=review[1],
                           to_id=review[2], to_name=review[3],
                           method="llm_review", similarity=review[4])

    conn.execute(
        "UPDATE normalization_review_queue SET status = 'resolved', resolution = ? WHERE id = ?",
        (action, review_id)
    )
    conn.commit()
