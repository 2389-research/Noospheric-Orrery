# ABOUTME: Materialized read-model of the /graph payload — build it once, serve
# ABOUTME: it cached, rather than recomputing (UMAP + big aggregations) per request.

"""Graph snapshot: precompute, don't recompute per request.

`GET /graph` used to recompute the whole cosmic_data_v4 payload on every
request (UMAP layout, big aggregation queries) and cache nothing — fine for a
small graph, but it got slow (and, worse, crash-prone under concurrent load)
once the graph grew past a few thousand entities. The graph only changes when
a job writes to it, so we compute the payload once (`build_graph_payload`) and
serve the cached blob; writers flip `graph_snapshot.dirty` (see `db.mark_graph_dirty`)
and a background task in `main.py` rebuilds.

Only the top `max_render_nodes` entities (by source_count) are included in the
rendered payload — the viz doesn't need to draw every entity to be legible, and
capping keeps both the rebuild and the JSON payload itself bounded.
"""

from __future__ import annotations

import json
from collections import defaultdict

GOLDEN_RATIO = 0.618033988749895
BASE_SATURATION = 65
BASE_LIGHTNESS = 62
DESAT_PER_LEVEL = 8

DEFAULT_MAX_RENDER_NODES = 3000


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


def _assign_domain_colors(domains: list[dict]) -> dict[str, str]:
    """Hierarchy-aware golden ratio color distribution — mirror of
    routes.graph._assign_domain_colors (kept separate to avoid a circular
    import between this module and the route that calls it)."""
    paths = [d["path"] for d in domains]
    if not paths:
        return {}

    parts_list = [p.split("/") for p in paths]
    branch_level = 0
    for level in range(min(len(p) for p in parts_list)):
        values = set(p[level] for p in parts_list)
        if len(values) > 1:
            break
        branch_level = level + 1

    top_level_names = sorted(set(
        "/".join(p.split("/")[:branch_level + 1]) for p in paths
    ))

    top_level_hues = {}
    for i, name in enumerate(top_level_names):
        top_level_hues[name] = (i / max(len(top_level_names), 1)) * 360

    slice_size = 360 / max(len(top_level_names), 1)

    color_map = {}
    for top_name in top_level_names:
        range_start = top_level_hues[top_name]
        family = sorted([p for p in paths if p.startswith(top_name)])
        for i, path in enumerate(family):
            offset = ((i * GOLDEN_RATIO) % 1) * slice_size
            hue = (range_start + offset) % 360
            depth = path.count("/") - branch_level
            saturation = max(30, BASE_SATURATION - depth * DESAT_PER_LEVEL)
            color_map[path] = _hsl_to_hex(hue, saturation, BASE_LIGHTNESS)

    return color_map


def build_graph_payload(store, *, max_render_nodes: int = DEFAULT_MAX_RENDER_NODES) -> dict:
    """Build the full cosmic_data_v4 payload from the store.

    Same computation as the old inline `/graph` handler — just extracted so it
    can be called from the cached path (`get_or_build`) instead of per-request.
    """
    from .domain_layout import ensure_layout

    domain_objs = store.domains.list(min_doc_count=1)
    domains = [{"id": d.id, "path": d.path, "parent_path": d.parent_path,
                "doc_count": d.document_count, "spec_version": d.spec_version} for d in domain_objs]

    domain_positions = ensure_layout(store)

    domain_doc_counts = {d["path"]: d["doc_count"] for d in domains}
    region_colors = _assign_domain_colors(domains)
    for d in domains:
        region = d["path"].split("/")[0]
        if region not in region_colors:
            region_colors[region] = region_colors.get(d["path"], "#81d4fa")

    subdomains = [d["path"] for d in domains if d["path"].count("/") >= 2]

    # Entities with domain weights — single batch query instead of N+1
    all_entities = store.entities.list(limit=max_render_nodes)
    weight_rows = store.conn.execute("""
        SELECT es.entity_id, dd.domain_path, COUNT(*) as weight
        FROM entity_sources es
        JOIN document_domains dd ON es.document_id = dd.document_id
        GROUP BY es.entity_id, dd.domain_path
    """).fetchall()

    raw_weights: dict[str, dict[str, int]] = defaultdict(dict)
    for r in weight_rows:
        raw_weights[r[0]][r[1]] = r[2]

    entity_domain_weights: dict[str, dict[str, float]] = {}
    for eid, dw in raw_weights.items():
        total = sum(dw.values())
        if total > 0:
            entity_domain_weights[eid] = {dp: round(w / total, 3) for dp, w in dw.items()}

    entities = []
    for e in all_entities:
        dw = entity_domain_weights.get(e.id, {})
        if not dw:
            continue
        entities.append({
            "entityId": e.id, "name": e.canonical_name, "type": e.type,
            "videoCount": e.source_count, "domainWeights": dw,
        })

    trade_routes = store.relationships.get_trade_routes()

    recent_docs = store.documents.get_recent(limit=50)
    videos = [{"id": d.id, "title": d.title, "domains": d.domains,
               "primary": d.domains[0] if d.domains else None,
               "content_type": getattr(d, "content_type", "text")} for d in recent_docs]

    domain_specs = {}
    for d in domains:
        domain_specs[d["path"]] = ({"spec_version": d["spec_version"]}
                                    if d["spec_version"] else None)

    running_jobs = store.jobs.list(status_filter="running")
    active_simmers = [j.target for j in running_jobs if j.type.startswith("simmer_")]

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
        "render_node_count": len(entities),
        "total_node_count": len(all_entities),
    }


# ── Snapshot persistence ────────────────────────────────────────────────

def is_dirty(store) -> bool:
    row = store.conn.execute(
        "SELECT dirty FROM graph_snapshot WHERE id = 'current'"
    ).fetchone()
    # No row yet → treat as dirty (needs a first build).
    return row is None or bool(row[0] if not hasattr(row, "keys") else row["dirty"])


def load_snapshot(store) -> dict | None:
    """Return the cached payload dict, or None if no snapshot has been built."""
    row = store.conn.execute(
        "SELECT payload FROM graph_snapshot WHERE id = 'current'"
    ).fetchone()
    if not row:
        return None
    payload = row[0] if not hasattr(row, "keys") else row["payload"]
    if not payload:
        return None
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None


def _set_dirty(store, value: int) -> None:
    store.conn.execute(
        "INSERT INTO graph_snapshot (id, dirty) VALUES ('current', ?) "
        "ON CONFLICT(id) DO UPDATE SET dirty = excluded.dirty",
        (value,),
    )
    store.conn.commit()


def save_snapshot(store, payload: dict) -> None:
    """Persist the payload (one logical row). Does NOT touch the dirty bit —
    the rebuild owns dirty (it clears it BEFORE building; see rebuild_snapshot)."""
    blob = json.dumps(payload)
    edge_count = len(payload.get("trade_routes", []))
    store.conn.execute(
        "INSERT INTO graph_snapshot (id, payload, built_at, entity_count, edge_count) "
        "VALUES ('current', ?, CURRENT_TIMESTAMP, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, "
        "built_at = excluded.built_at, entity_count = excluded.entity_count, "
        "edge_count = excluded.edge_count",
        (blob, payload.get("total_node_count", 0), edge_count),
    )
    store.conn.commit()


def rebuild_snapshot(store, *, max_render_nodes: int = DEFAULT_MAX_RENDER_NODES) -> dict:
    """Build the payload from the store and persist it.

    Clears `dirty` BEFORE building, not after. The build takes seconds; a writer
    that commits + flips dirty during that window must NOT have its flag cleared
    by our post-build write (or its change would stay invisible until the next
    unrelated write). Clearing up-front means such a write leaves dirty=1, so the
    next sweep rebuilds. On build failure we re-flag so the sweep retries.
    """
    _set_dirty(store, 0)
    try:
        payload = build_graph_payload(store, max_render_nodes=max_render_nodes)
        save_snapshot(store, payload)
        return payload
    except Exception:
        _set_dirty(store, 1)
        raise


def get_or_build(store, *, max_render_nodes: int = DEFAULT_MAX_RENDER_NODES) -> dict:
    """Serve the cached snapshot; build inline on the first-ever request.

    Does NOT rebuild on a stale (dirty) snapshot — the background task owns
    that, and serving seconds-stale data is fine for a knowledge map. Only a
    completely missing snapshot triggers an inline build.
    """
    cached = load_snapshot(store)
    if cached is not None:
        return cached
    return rebuild_snapshot(store, max_render_nodes=max_render_nodes)
