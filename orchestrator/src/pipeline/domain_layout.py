"""UMAP-based domain layout with persistence.

Supports both DataStore (Firestore) and raw sqlite3.Connection.
"""

from __future__ import annotations
import pickle
import sqlite3
import numpy as np
from sentence_transformers import SentenceTransformer
import umap

_model = None

def _get_embed_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _is_store(obj):
    return hasattr(obj, 'domains') and hasattr(obj, 'layout')


def _build_domain_text_store(store, domain_path):
    """Build embedding input using repository methods."""
    # Get doc titles
    docs = store.documents.get_for_domain(domain_path)
    titles = [d.title for d in docs[:6] if d.title]

    # Get entity names
    ents = store.entities.get_for_domain(domain_path, limit=12)
    entity_names = [e.canonical_name for e in ents]

    return f"{domain_path.replace('/', ' ')}. {' '.join(titles[:6])}. {' '.join(entity_names[:12])}"


def _build_domain_text_conn(conn, domain_path):
    """Build embedding input using raw SQL."""
    doc_titles = conn.execute("""
        SELECT d.title FROM documents d
        JOIN document_domains dd ON d.id = dd.document_id
        WHERE dd.domain_path = ?
        ORDER BY d.created_at DESC LIMIT 6
    """, (domain_path,)).fetchall()
    titles = [r[0] for r in doc_titles if r[0]]

    entity_names = conn.execute("""
        SELECT e.canonical_name FROM entities e
        JOIN entity_sources es ON e.id = es.entity_id
        JOIN document_domains dd ON es.document_id = dd.document_id
        WHERE dd.domain_path = ?
        GROUP BY e.id
        ORDER BY COUNT(*) DESC LIMIT 12
    """, (domain_path,)).fetchall()
    entities = [r[0] for r in entity_names]

    return f"{domain_path.replace('/', ' ')}. {' '.join(titles[:6])}. {' '.join(entities[:12])}"


def _build_domain_text(store_or_conn, domain_path):
    if _is_store(store_or_conn):
        return _build_domain_text_store(store_or_conn, domain_path)
    return _build_domain_text_conn(store_or_conn, domain_path)


def _get_domain_paths(store_or_conn):
    if _is_store(store_or_conn):
        domains = store_or_conn.domains.list(min_doc_count=1)
        return [d.path for d in domains]
    rows = store_or_conn.execute(
        "SELECT path FROM domains WHERE document_count > 0 ORDER BY path"
    ).fetchall()
    return [r[0] for r in rows]


def _get_stored_positions(store_or_conn):
    if _is_store(store_or_conn):
        return store_or_conn.layout.get_stored_positions()
    rows = store_or_conn.execute("SELECT domain_path, x, y FROM domain_layout").fetchall()
    return {r[0]: {"x": r[1], "y": r[2]} for r in rows}


def _store_position(store_or_conn, domain_path, x, y, embedding=None):
    if _is_store(store_or_conn):
        store_or_conn.layout.store_position(domain_path, x, y, embedding)
    else:
        store_or_conn.execute(
            "INSERT OR REPLACE INTO domain_layout (domain_path, x, y, embedding) VALUES (?, ?, ?, ?)",
            (domain_path, x, y, embedding))
        store_or_conn.commit()


def _store_model(store_or_conn, model_blob, domain_count):
    if _is_store(store_or_conn):
        store_or_conn.layout.store_model(model_blob, domain_count)
    else:
        store_or_conn.execute(
            "INSERT OR REPLACE INTO layout_model (id, model_blob, domain_count) VALUES (?, ?, ?)",
            ("umap", model_blob, domain_count))
        store_or_conn.commit()


def _get_model(store_or_conn):
    if _is_store(store_or_conn):
        return store_or_conn.layout.get_model()
    row = store_or_conn.execute("SELECT model_blob, domain_count FROM layout_model WHERE id = 'umap'").fetchone()
    if not row or not row[0]:
        return None
    return {"model_blob": row[0], "domain_count": row[1]}


def _delete_position(store_or_conn, domain_path):
    if _is_store(store_or_conn):
        store_or_conn.layout.delete_position(domain_path)
    else:
        store_or_conn.execute("DELETE FROM domain_layout WHERE domain_path = ?", (domain_path,))
        store_or_conn.commit()


def _get_domain_count(store_or_conn):
    if _is_store(store_or_conn):
        return len(store_or_conn.domains.list(min_doc_count=1))
    return store_or_conn.execute("SELECT COUNT(*) FROM domains WHERE document_count > 0").fetchone()[0]


def full_fit(store_or_conn):
    """Run full UMAP fit on all domains. Stores positions + model."""
    paths = _get_domain_paths(store_or_conn)

    if len(paths) < 3:
        positions = {}
        for i, path in enumerate(paths):
            positions[path] = {"x": (i + 1) / (len(paths) + 1), "y": 0.5}
            _store_position(store_or_conn, path, positions[path]["x"], positions[path]["y"])
        return positions

    model = _get_embed_model()
    texts = [_build_domain_text(store_or_conn, p) for p in paths]
    embeddings = model.encode(texts, normalize_embeddings=True)

    n_neighbors = min(15, len(paths) - 1)
    reducer = umap.UMAP(
        n_components=2, n_neighbors=n_neighbors,
        min_dist=0.15, spread=2.5, metric="cosine", random_state=42,
    )
    coords = reducer.fit_transform(embeddings)

    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1

    positions = {}
    for i, path in enumerate(paths):
        x = float((coords[i, 0] - mins[0]) / ranges[0])
        y = float((coords[i, 1] - mins[1]) / ranges[1])
        positions[path] = {"x": x, "y": y}
        _store_position(store_or_conn, path, x, y, embeddings[i].tobytes())

    model_data = {"reducer": reducer, "mins": mins, "maxs": maxs, "ranges": ranges}
    _store_model(store_or_conn, pickle.dumps(model_data), len(paths))

    return positions


def transform_new_domain(store_or_conn, domain_path):
    """Place a new domain using the saved UMAP model."""
    model_data = _get_model(store_or_conn)
    if not model_data or not model_data.get("model_blob"):
        return None

    data = pickle.loads(model_data["model_blob"])
    saved_count = model_data.get("domain_count", 0)

    current_count = _get_domain_count(store_or_conn)
    if current_count >= saved_count * 2:
        full_fit(store_or_conn)
        stored = _get_stored_positions(store_or_conn)
        return stored.get(domain_path)

    embed_model = _get_embed_model()
    text = _build_domain_text(store_or_conn, domain_path)
    embedding = embed_model.encode([text], normalize_embeddings=True)

    coords = data["reducer"].transform(embedding)
    x = float(np.clip((coords[0, 0] - data["mins"][0]) / data["ranges"][0], 0, 1))
    y = float(np.clip((coords[0, 1] - data["mins"][1]) / data["ranges"][1], 0, 1))

    _store_position(store_or_conn, domain_path, x, y, embedding[0].tobytes())
    return {"x": x, "y": y}


def ensure_layout(store_or_conn):
    """Get positions, computing if needed. Main entry point for /graph."""
    all_paths = set(_get_domain_paths(store_or_conn))
    stored = _get_stored_positions(store_or_conn)
    stored_paths = set(stored.keys())

    # Remove stale
    for path in stored_paths - all_paths:
        _delete_position(store_or_conn, path)
        del stored[path]

    missing = all_paths - stored_paths

    if not stored or len(missing) > len(all_paths) * 0.5:
        return full_fit(store_or_conn)

    if missing:
        for path in missing:
            pos = transform_new_domain(store_or_conn, path)
            if pos:
                stored[path] = pos

    return stored
