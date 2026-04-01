"""UMAP-based domain layout with persistence.

- Full fit: embed all domains, run UMAP, store positions + model
- Transform: embed new domain, use saved UMAP model to place it, store position
- Positions are stable — existing domains don't move when new ones are added
- Periodic re-fit when domain count doubles (resets all positions)
- Falls back to hash-based positioning if UMAP/numba fails at runtime
"""

import hashlib
import logging
import pickle
import sqlite3
import numpy as np
from sentence_transformers import SentenceTransformer
import umap

logger = logging.getLogger(__name__)

_model = None

def _get_embed_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _build_domain_text(conn: sqlite3.Connection, domain_path: str) -> str:
    """Build embedding input for a domain: path + top doc titles + top entity names."""
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


def _fallback_position(domain_path: str, stored: dict[str, dict] | None = None) -> dict:
    """Deterministic fallback position from domain path hash, near parent if possible."""
    # Try to place near parent domain
    parent = "/".join(domain_path.split("/")[:-1])
    if stored and parent in stored:
        h = hashlib.md5(domain_path.encode()).digest()
        dx = (h[0] / 255 - 0.5) * 0.15
        dy = (h[1] / 255 - 0.5) * 0.15
        return {
            "x": max(0, min(1, stored[parent]["x"] + dx)),
            "y": max(0, min(1, stored[parent]["y"] + dy)),
        }
    # No parent — hash to full unit square
    h = hashlib.md5(domain_path.encode()).digest()
    return {"x": h[0] / 255 * 0.8 + 0.1, "y": h[1] / 255 * 0.8 + 0.1}


def get_stored_positions(conn: sqlite3.Connection) -> dict[str, dict]:
    """Get all stored domain positions."""
    rows = conn.execute("SELECT domain_path, x, y FROM domain_layout").fetchall()
    return {r[0]: {"x": r[1], "y": r[2]} for r in rows}


def full_fit(conn: sqlite3.Connection) -> dict[str, dict]:
    """Run full UMAP fit on all domains. Stores positions + model."""
    domains = conn.execute(
        "SELECT path FROM domains WHERE document_count > 0 ORDER BY path"
    ).fetchall()
    paths = [r[0] for r in domains]

    if len(paths) < 3:
        # Not enough for UMAP — place in a line
        positions = {}
        for i, path in enumerate(paths):
            positions[path] = {"x": (i + 1) / (len(paths) + 1), "y": 0.5}
        _store_positions(conn, positions)
        return positions

    # Build texts and embed
    model = _get_embed_model()
    texts = [_build_domain_text(conn, p) for p in paths]
    embeddings = model.encode(texts, normalize_embeddings=True)

    # UMAP fit — with fallback if numba/UMAP fails at runtime
    try:
        n_neighbors = min(15, len(paths) - 1)
        reducer = umap.UMAP(
            n_components=2,
            n_neighbors=n_neighbors,
            min_dist=0.15,
            spread=2.5,
            metric="cosine",
            random_state=42,
        )
        coords = reducer.fit_transform(embeddings)
    except Exception as e:
        logger.warning("UMAP fit failed (%s), using fallback positions", e)
        positions = {}
        for path in paths:
            positions[path] = _fallback_position(path, positions)
        _store_positions(conn, positions)
        return positions

    # Normalize to 0-1
    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1

    positions = {}
    for i, path in enumerate(paths):
        x = float((coords[i, 0] - mins[0]) / ranges[0])
        y = float((coords[i, 1] - mins[1]) / ranges[1])
        positions[path] = {"x": x, "y": y}

    # Store positions + embeddings
    _store_positions(conn, positions)
    for i, path in enumerate(paths):
        conn.execute(
            "INSERT OR REPLACE INTO domain_layout (domain_path, x, y, embedding) VALUES (?, ?, ?, ?)",
            (path, positions[path]["x"], positions[path]["y"], embeddings[i].tobytes())
        )

    # Store the UMAP model + normalization params
    model_data = {
        "reducer": reducer,
        "mins": mins,
        "maxs": maxs,
        "ranges": ranges,
    }
    conn.execute(
        "INSERT OR REPLACE INTO layout_model (id, model_blob, domain_count) VALUES (?, ?, ?)",
        ("umap", pickle.dumps(model_data), len(paths))
    )
    conn.commit()

    return positions


def transform_new_domain(conn: sqlite3.Connection, domain_path: str) -> dict | None:
    """Place a new domain using the saved UMAP model. Returns {"x", "y"} or None."""
    # Load saved model
    row = conn.execute("SELECT model_blob, domain_count FROM layout_model WHERE id = 'umap'").fetchone()
    if not row or not row[0]:
        return None

    model_data = pickle.loads(row[0])
    reducer = model_data["reducer"]
    mins = model_data["mins"]
    ranges = model_data["ranges"]
    saved_count = row[1] or 0

    # Check if we should re-fit (domain count doubled)
    current_count = conn.execute(
        "SELECT COUNT(*) FROM domains WHERE document_count > 0"
    ).fetchone()[0]
    if current_count >= saved_count * 2:
        # Re-fit everything
        full_fit(conn)
        pos = conn.execute(
            "SELECT x, y FROM domain_layout WHERE domain_path = ?", (domain_path,)
        ).fetchone()
        return {"x": pos[0], "y": pos[1]} if pos else None

    # Embed the new domain
    embed_model = _get_embed_model()
    text = _build_domain_text(conn, domain_path)
    embedding = embed_model.encode([text], normalize_embeddings=True)

    # Transform with saved UMAP — fallback if numba/UMAP fails
    try:
        coords = reducer.transform(embedding)
        x = float(np.clip((coords[0, 0] - mins[0]) / ranges[0], 0, 1))
        y = float(np.clip((coords[0, 1] - mins[1]) / ranges[1], 0, 1))
    except Exception as e:
        logger.warning("UMAP transform failed for %s (%s), using fallback", domain_path, e)
        stored = get_stored_positions(conn)
        fallback = _fallback_position(domain_path, stored)
        x, y = fallback["x"], fallback["y"]

    # Store
    conn.execute(
        "INSERT OR REPLACE INTO domain_layout (domain_path, x, y, embedding) VALUES (?, ?, ?, ?)",
        (domain_path, x, y, embedding[0].tobytes())
    )
    conn.commit()

    return {"x": x, "y": y}


def ensure_layout(conn: sqlite3.Connection) -> dict[str, dict]:
    """Get positions, computing if needed. Main entry point for /graph."""
    # Get domains that need positions
    all_domains = conn.execute(
        "SELECT path FROM domains WHERE document_count > 0 ORDER BY path"
    ).fetchall()
    all_paths = set(r[0] for r in all_domains)

    stored = get_stored_positions(conn)
    stored_paths = set(stored.keys())

    # Remove stale positions (domains that no longer exist)
    stale = stored_paths - all_paths
    if stale:
        for path in stale:
            conn.execute("DELETE FROM domain_layout WHERE domain_path = ?", (path,))
            del stored[path]
        conn.commit()

    missing = all_paths - stored_paths

    if not stored or len(missing) > len(all_paths) * 0.5:
        # No positions or too many missing — full fit
        return full_fit(conn)

    if missing:
        # A few new domains — transform them
        for path in missing:
            pos = transform_new_domain(conn, path)
            if pos:
                stored[path] = pos

    return stored


def _store_positions(conn: sqlite3.Connection, positions: dict[str, dict]):
    """Bulk store positions."""
    for path, pos in positions.items():
        conn.execute(
            "INSERT OR REPLACE INTO domain_layout (domain_path, x, y) VALUES (?, ?, ?)",
            (path, pos["x"], pos["y"])
        )
    conn.commit()
