"""Serve graph data in cosmic_data_v4 format for the visualization."""

import math
import numpy as np
from collections import defaultdict
from fastapi import APIRouter, Depends
from ..config import get_settings
from ..dependencies import get_auth_store, AuthStore
from ..repositories.factory import get_store

router = APIRouter()

GOLDEN_RATIO = 0.618033988749895
BASE_SATURATION = 65
BASE_LIGHTNESS = 62
DESAT_PER_LEVEL = 8


def _assign_domain_colors(domains: list[dict]) -> dict[str, str]:
    """Hierarchy-aware golden ratio color distribution.

    Top-level domains each own an equal slice of the hue wheel.
    Within each slice, subdomains are spaced using the golden ratio
    for maximum perceptual distance. Deeper domains desaturate slightly.
    """
    paths = [d["path"] for d in domains]
    if not paths:
        return {}

    # Find top-level domains (the level where paths actually branch)
    parts_list = [p.split("/") for p in paths]
    # Find branching level
    branch_level = 0
    for level in range(min(len(p) for p in parts_list)):
        values = set(p[level] for p in parts_list)
        if len(values) > 1:
            break
        branch_level = level + 1

    # Group by the branching segment
    top_level_names = sorted(set(
        "/".join(p.split("/")[:branch_level + 1]) for p in paths
    ))

    # Divide hue wheel evenly among top-level groups
    top_level_hues = {}
    for i, name in enumerate(top_level_names):
        top_level_hues[name] = (i / max(len(top_level_names), 1)) * 360

    slice_size = 360 / max(len(top_level_names), 1)

    # Assign colors within each slice using golden ratio
    color_map = {}
    for top_name in top_level_names:
        range_start = top_level_hues[top_name]

        # All domains in this family, sorted for determinism
        family = sorted([p for p in paths if p.startswith(top_name)])

        for i, path in enumerate(family):
            offset = ((i * GOLDEN_RATIO) % 1) * slice_size
            hue = (range_start + offset) % 360

            # Depth-based desaturation
            depth = path.count("/") - branch_level
            saturation = max(30, BASE_SATURATION - depth * DESAT_PER_LEVEL)

            color_map[path] = _hsl_to_hex(hue, saturation, BASE_LIGHTNESS)

    return color_map


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """Convert HSL (h: 0-360, s: 0-100, l: 0-100) to hex color."""
    s /= 100
    l /= 100
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2

    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    r, g, b = int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def _layout_domains(domains: list[dict]) -> dict[str, dict]:
    """Layout domains in a hierarchy. Top-level parents in a circle,
    children orbit near their parent.

    Finds the "branching level" — the depth where domains actually diverge.
    For a corpus where everything is under business/, the branching happens
    at level 2 (fundraising, operations, product_development, venture_capital).
    """
    positions = {}
    if not domains:
        return positions

    paths = [d["path"] for d in domains]

    # Find the branching level — deepest common prefix
    # e.g., all paths start with "business/" so level 0 is shared
    parts = [p.split("/") for p in paths]
    branch_level = 0
    for level in range(min(len(p) for p in parts)):
        values_at_level = set(p[level] for p in parts)
        if len(values_at_level) > 1:
            break
        branch_level = level + 1

    # Group by the branching segment
    groups: dict[str, list[dict]] = {}
    for d in domains:
        segs = d["path"].split("/")
        if len(segs) > branch_level:
            group_key = "/".join(segs[:branch_level + 1])
        else:
            group_key = d["path"]
        groups.setdefault(group_key, []).append(d)

    # Place groups in a circle
    group_keys = sorted(groups.keys())
    n = max(len(group_keys), 1)
    for i, gk in enumerate(group_keys):
        angle = (2 * math.pi * i) / n - math.pi / 2  # start from top
        gx = 0.5 + 0.32 * math.cos(angle)
        gy = 0.5 + 0.32 * math.sin(angle)

        members = groups[gk]
        if len(members) == 1:
            positions[members[0]["path"]] = {"x": gx, "y": gy}
        else:
            # Place group members in a small cluster
            for j, d in enumerate(members):
                sub_angle = angle + (j - len(members) / 2) * 0.3
                dist = 0.32 + 0.04 * (j % 3) + 0.02
                positions[d["path"]] = {
                    "x": 0.5 + dist * math.cos(sub_angle),
                    "y": 0.5 + dist * math.sin(sub_angle),
                }

    return positions


@router.get("/graph")
def get_graph_data(auth: AuthStore = Depends(get_auth_store)):
    """Return graph data in cosmic_data_v4 format."""
    store = auth.store

    # Get all domains with docs
    domain_objs = store.domains.list(min_doc_count=1)
    domains = [{"id": d.id, "path": d.path, "parent_path": d.parent_path,
                "doc_count": d.document_count, "spec_version": d.spec_version} for d in domain_objs]

    # Domain positions — read from stored positions
    # On SQLite: UMAP computes if needed. On Firestore: positions pre-pushed, just read.
    if store.conn is not None:
        from ..pipeline.domain_layout import ensure_layout
        domain_positions = ensure_layout(store)
    else:
        domain_positions = store.layout.get_stored_positions()
        # Place any domains without positions in a circle
        import math
        missing = [d["path"] for d in domains if d["path"] not in domain_positions]
        for i, path in enumerate(missing):
            angle = (i / max(len(missing), 1)) * 2 * math.pi
            x = 0.5 + 0.3 * math.cos(angle)
            y = 0.5 + 0.3 * math.sin(angle)
            domain_positions[path] = {"x": x, "y": y}
            store.layout.store_position(path, x, y)

    domain_doc_counts = {d["path"]: d["doc_count"] for d in domains}
    region_colors = _assign_domain_colors(domains)
    for d in domains:
        region = d["path"].split("/")[0]
        if region not in region_colors:
            region_colors[region] = region_colors.get(d["path"], "#81d4fa")

    subdomains = [d["path"] for d in domains if d["path"].count("/") >= 2]

    # Entities with domain weights
    all_entities = store.entities.list(limit=5000)
    entities = []
    for e in all_entities:
        domain_weights = store.domains.get_entity_domain_weights(e.id)
        if not domain_weights:
            continue
        entities.append({
            "entityId": e.id, "name": e.canonical_name, "type": e.type,
            "videoCount": e.source_count, "domainWeights": domain_weights,
        })

    # Trade routes
    trade_routes = store.relationships.get_trade_routes()

    # Recent documents
    recent_docs = store.documents.get_recent(limit=50)
    videos = [{"id": d.id, "title": d.title, "domains": d.domains,
               "primary": d.domains[0] if d.domains else None} for d in recent_docs]

    # Domain specs
    domain_specs = {}
    for d in domains:
        if d["spec_version"]:
            domain_specs[d["path"]] = {"spec_version": d["spec_version"]}
        else:
            domain_specs[d["path"]] = None

    # Active simmers
    running_jobs = store.jobs.list(status_filter="running")
    active_simmers = [j.target for j in running_jobs if j.type.startswith("simmer_")]

    store.close()

    return {
        "domain_positions": domain_positions,
        "domain_video_counts": domain_doc_counts,
        "domain_specs": domain_specs,
        "active_simmers": active_simmers,
        "region_colors": region_colors,
        "subdomains": subdomains,
        "videos": videos,
        "entities": entities,
        "v3_entities": [],
        "trade_routes": trade_routes,
    }


def _layout_domains_umap(domains: list[dict], conn) -> dict[str, dict]:
    """Layout domains using UMAP on semantic embeddings.

    Each domain is embedded as: domain_path + top doc titles + top entity names.
    UMAP reduces to 2D. Domains that share content cluster together.
    """
    from sentence_transformers import SentenceTransformer
    import umap

    if len(domains) < 3:
        # UMAP needs at least 3 points; fall back to circular
        return _layout_domains(domains)

    model = SentenceTransformer("all-MiniLM-L6-v2")

    # Build embedding input for each domain
    texts = []
    for d in domains:
        path = d["path"]

        # Top doc titles for this domain
        doc_titles = conn.execute("""
            SELECT d.title FROM documents d
            JOIN document_domains dd ON d.id = dd.document_id
            WHERE dd.domain_path = ?
            ORDER BY d.created_at DESC LIMIT 6
        """, (path,)).fetchall()
        titles = [r[0] for r in doc_titles if r[0]]

        # Top entity names for this domain
        entity_names = conn.execute("""
            SELECT e.canonical_name FROM entities e
            JOIN entity_sources es ON e.id = es.entity_id
            JOIN document_domains dd ON es.document_id = dd.document_id
            WHERE dd.domain_path = ?
            GROUP BY e.id
            ORDER BY COUNT(*) DESC LIMIT 12
        """, (path,)).fetchall()
        entities = [r[0] for r in entity_names]

        # Concat: path + titles + entities
        text = f"{path.replace('/', ' ')}. {' '.join(titles[:6])}. {' '.join(entities[:12])}"
        texts.append(text)

    # Embed
    embeddings = model.encode(texts, normalize_embeddings=True)

    # UMAP to 2D
    n_neighbors = min(15, len(domains) - 1)
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=0.15,
        spread=2.5,
        metric="cosine",
        random_state=42,
    )
    coords = reducer.fit_transform(embeddings)

    # Normalize to 0-1 range
    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1  # avoid division by zero

    positions = {}
    for i, d in enumerate(domains):
        positions[d["path"]] = {
            "x": float((coords[i, 0] - mins[0]) / ranges[0]),
            "y": float((coords[i, 1] - mins[1]) / ranges[1]),
        }

    return positions


@router.get("/graph/umap")
def get_graph_data_umap(auth: AuthStore = Depends(get_auth_store)):
    """Same as /graph but with UMAP-based domain positions."""
    settings = get_settings()
    store = auth.store
    conn = store.conn

    domains_raw = conn.execute(
        "SELECT id, path, parent_path, document_count, spec_version FROM domains WHERE document_count > 0 ORDER BY path"
    ).fetchall()
    domains = [{"id": r[0], "path": r[1], "parent_path": r[2], "doc_count": r[3], "spec_version": r[4]} for r in domains_raw]

    # UMAP positions instead of circular
    domain_positions = _layout_domains_umap(domains, conn)

    # Everything else same as /graph
    domain_doc_counts = {d["path"]: d["doc_count"] for d in domains}
    region_colors = _assign_domain_colors(domains)
    for d in domains:
        region = d["path"].split("/")[0]
        if region not in region_colors:
            region_colors[region] = region_colors.get(d["path"], "#81d4fa")

    subdomains = [d["path"] for d in domains if d["path"].count("/") >= 2]

    entities_raw = conn.execute("""
        SELECT e.id, e.canonical_name, e.type,
               (SELECT COUNT(*) FROM entity_sources es WHERE es.entity_id = e.id) as source_count
        FROM entities e ORDER BY source_count DESC
    """).fetchall()

    entities = []
    for e in entities_raw:
        domain_weights_raw = conn.execute("""
            SELECT dd.domain_path, COUNT(*) as weight
            FROM entity_sources es
            JOIN document_domains dd ON es.document_id = dd.document_id
            WHERE es.entity_id = ?
            GROUP BY dd.domain_path
        """, (e[0],)).fetchall()
        if not domain_weights_raw:
            continue
        total = sum(r[1] for r in domain_weights_raw)
        domain_weights = {r[0]: round(r[1] / total, 3) for r in domain_weights_raw}
        entities.append({
            "entityId": e[0], "name": e[1], "type": e[2],
            "videoCount": e[3], "domainWeights": domain_weights,
        })

    shared = conn.execute("""
        SELECT dd1.domain_path, dd2.domain_path, COUNT(*) as weight
        FROM entity_sources es1
        JOIN entity_sources es2 ON es1.entity_id = es2.entity_id AND es1.document_id != es2.document_id
        JOIN document_domains dd1 ON es1.document_id = dd1.document_id
        JOIN document_domains dd2 ON es2.document_id = dd2.document_id
        WHERE dd1.domain_path < dd2.domain_path
        GROUP BY dd1.domain_path, dd2.domain_path
    """).fetchall()
    trade_routes = [{"source": r[0], "target": r[1], "weight": r[2]} for r in shared]

    domain_specs = {}
    for d in domains:
        domain_specs[d["path"]] = {"spec_version": d["spec_version"]} if d["spec_version"] else None

    active_jobs = conn.execute(
        "SELECT target FROM jobs WHERE type LIKE 'simmer_%' AND status = 'running'"
    ).fetchall()
    active_simmers = [r[0] for r in active_jobs]

    store.close()

    return {
        "domain_positions": domain_positions,
        "domain_video_counts": domain_doc_counts,
        "domain_specs": domain_specs,
        "active_simmers": active_simmers,
        "region_colors": region_colors,
        "subdomains": subdomains,
        "entities": entities,
        "trade_routes": trade_routes,
    }
