"""UMAP-based domain layout with anchor domains for stable positioning.

Uses 100 pre-defined anchor domains to establish a well-distributed semantic
space on the first fit. User domains slot into meaningful positions from the
start, regardless of what they upload first.

New domains added after the initial fit are placed via embedding similarity
to the nearest positioned domain (no UMAP transform() call — avoids the
NUMBA_DISABLE_JIT / ARM Docker incompatibility).
"""

from __future__ import annotations
import json
import pickle
import sqlite3
from pathlib import Path
import numpy as np


# Anchor domains for UMAP space initialization
_ANCHORS_PATH = Path(__file__).resolve().parent.parent.parent / "specs" / "universal_domains.json"
_ANCHOR_DOMAINS: list[str] | None = None


def _get_anchor_domains() -> list[str]:
    """Load the 100 universal anchor domains."""
    global _ANCHOR_DOMAINS
    if _ANCHOR_DOMAINS is None:
        with open(_ANCHORS_PATH) as f:
            data = json.load(f)
        _ANCHOR_DOMAINS = data["domains"]
    return _ANCHOR_DOMAINS


def _embed_texts(texts: list[str]) -> np.ndarray | None:
    """Embed texts using sentence-transformers.

    Returns None if sentence-transformers is not available.
    """
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model.encode(texts, normalize_embeddings=True)
    except ImportError:
        return None


def _is_store(obj):
    return hasattr(obj, 'domains') and hasattr(obj, 'layout')


def _build_domain_text_store(store, domain_path):
    """Build embedding input using repository methods."""
    docs = store.documents.get_for_domain(domain_path)
    titles = [d.title for d in docs[:6] if d.title]
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


def _get_stored_embeddings(store_or_conn) -> dict[str, np.ndarray]:
    """Get stored embeddings for positioned domains."""
    if _is_store(store_or_conn):
        # DataStore interface — would need a method for this
        return {}
    rows = store_or_conn.execute(
        "SELECT domain_path, embedding FROM domain_layout WHERE embedding IS NOT NULL"
    ).fetchall()
    result = {}
    for path, emb_bytes in rows:
        if emb_bytes:
            result[path] = np.frombuffer(emb_bytes, dtype=np.float32)
    return result


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


def _circular_layout(paths):
    """Fallback: place domains in a circle."""
    import math
    positions = {}
    for i, path in enumerate(paths):
        angle = (2 * math.pi * i) / max(len(paths), 1)
        positions[path] = {
            "x": 0.5 + 0.35 * math.cos(angle),
            "y": 0.5 + 0.35 * math.sin(angle),
        }
    return positions


def full_fit(store_or_conn):
    """Run UMAP fit on user domains + anchor domains for a well-distributed space.

    Anchor domains (100 diverse topics) are included in the fit to establish
    a stable semantic space. Only user domain positions are stored and returned.
    """
    user_paths = _get_domain_paths(store_or_conn)

    if not user_paths:
        return {}

    if len(user_paths) < 2:
        positions = {}
        for i, path in enumerate(user_paths):
            positions[path] = {"x": 0.5, "y": 0.5}
            _store_position(store_or_conn, path, 0.5, 0.5)
        return positions

    # Build texts: user domains get rich text (titles + entities), anchors get path only
    anchor_paths = _get_anchor_domains()
    # Exclude anchors that overlap with user paths
    anchor_paths = [a for a in anchor_paths if a not in set(user_paths)]

    user_texts = [_build_domain_text(store_or_conn, p) for p in user_paths]
    anchor_texts = [p.replace("/", " ").replace("-", " ") for p in anchor_paths]

    all_texts = user_texts + anchor_texts
    all_paths = user_paths + anchor_paths

    embeddings = _embed_texts(all_texts)
    if embeddings is None:
        positions = _circular_layout(user_paths)
        for path, pos in positions.items():
            _store_position(store_or_conn, path, pos["x"], pos["y"])
        return positions

    import umap
    n_points = len(all_paths)
    n_neighbors = min(15, n_points - 1)
    init_method = "random" if n_points < 10 else "spectral"

    try:
        reducer = umap.UMAP(
            n_components=2, n_neighbors=n_neighbors,
            min_dist=0.15, spread=2.5, metric="cosine",
            random_state=42, init=init_method,
        )
        coords = reducer.fit_transform(embeddings)
    except Exception as e:
        print(f"[domain_layout] UMAP fit_transform failed, falling back to circular layout: {type(e).__name__}: {e}", flush=True)
        positions = _circular_layout(user_paths)
        for path, pos in positions.items():
            _store_position(store_or_conn, path, pos["x"], pos["y"])
        return positions

    # Normalize ALL coordinates (anchors + user) to 0-1 together
    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1

    # Store only user domain positions (not anchors)
    positions = {}
    n_user = len(user_paths)
    for i in range(n_user):
        path = user_paths[i]
        x = float((coords[i, 0] - mins[0]) / ranges[0])
        y = float((coords[i, 1] - mins[1]) / ranges[1])
        positions[path] = {"x": x, "y": y}
        _store_position(store_or_conn, path, x, y, embeddings[i].tobytes())

    # Store reducer + normalization params for transform() on new domains
    model_data = {"reducer": reducer, "mins": mins, "maxs": maxs, "ranges": ranges}
    _store_model(store_or_conn, pickle.dumps(model_data), n_user)

    return positions


def transform_new_domain(store_or_conn, domain_path):
    """Place a new domain using the saved UMAP model via transform().

    Requires NUMBA_CPU_NAME=generic in Docker to avoid SIGILL (numba#10388).
    Falls back to embedding similarity if transform fails.
    """
    model_data = _get_model(store_or_conn)
    if not model_data or not model_data.get("model_blob"):
        return None

    text = _build_domain_text(store_or_conn, domain_path)
    embedding = _embed_texts([text])
    if embedding is None:
        return None

    try:
        data = pickle.loads(model_data["model_blob"])
        coords = data["reducer"].transform(embedding)
        x = float(np.clip((coords[0, 0] - data["mins"][0]) / data["ranges"][0], 0, 1))
        y = float(np.clip((coords[0, 1] - data["mins"][1]) / data["ranges"][1], 0, 1))
        _store_position(store_or_conn, domain_path, x, y, embedding[0].tobytes())
        return {"x": x, "y": y}
    except Exception as e:
        print(f"UMAP transform failed for {domain_path}, using similarity fallback: {e}", flush=True)

    # Fallback: place near most similar existing domain
    stored_embeddings = _get_stored_embeddings(store_or_conn)
    stored_positions = _get_stored_positions(store_or_conn)
    if not stored_embeddings:
        return None

    new_vec = embedding[0]
    best_path = None
    best_sim = -1.0
    for path, emb in stored_embeddings.items():
        if path not in stored_positions:
            continue
        sim = float(np.dot(new_vec, emb) / (np.linalg.norm(new_vec) * np.linalg.norm(emb) + 1e-8))
        if sim > best_sim:
            best_sim = sim
            best_path = path

    if best_path is None:
        return None

    anchor_pos = stored_positions[best_path]
    h = hash(domain_path)
    angle = (h % 360) * (3.14159 / 180)
    dist = 0.02 + 0.06 * (1.0 - best_sim)
    import math
    x = float(np.clip(anchor_pos["x"] + dist * math.cos(angle), 0.02, 0.98))
    y = float(np.clip(anchor_pos["y"] + dist * math.sin(angle), 0.02, 0.98))
    _store_position(store_or_conn, domain_path, x, y, embedding[0].tobytes())
    return {"x": x, "y": y}


def ensure_layout(store_or_conn):
    """Get positions, computing if needed. Main entry point for /graph.

    - First call: fit_transform with anchor domains for a well-distributed space
    - Subsequent calls: read stored positions
    - New domains: UMAP transform() to place in the existing space (stable positions)
    - Fallback: embedding similarity if transform fails
    """
    all_paths = set(_get_domain_paths(store_or_conn))
    stored = _get_stored_positions(store_or_conn)
    stored_paths = set(stored.keys())

    # Remove stale positions for domains that no longer exist
    for path in stored_paths - all_paths:
        _delete_position(store_or_conn, path)
        del stored[path]

    missing = all_paths - stored_paths

    # Full re-fit if no positions exist or majority of domains are new
    if not stored or len(missing) > len(all_paths) * 0.5:
        return full_fit(store_or_conn)

    # Place individual new domains via transform (or similarity fallback)
    if missing:
        for path in missing:
            pos = transform_new_domain(store_or_conn, path)
            if pos:
                stored[path] = pos

    return stored
