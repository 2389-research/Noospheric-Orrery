"""Serve graph data in cosmic_data_v4 format for the visualization."""

import math
from collections import defaultdict
from fastapi import APIRouter
from ..config import get_settings
from ..db import get_connection

router = APIRouter()

# Base hues for top-level regions (0-360)
REGION_BASE_HUE = {
    "business": 25,      # orange
    "technology": 170,   # teal
    "science": 200,      # blue
    "creative": 290,     # purple
    "education": 45,     # yellow
    "health": 130,       # green
    "social": 210,       # slate blue
}
DEFAULT_HUE = 220


def _domain_color(path: str) -> str:
    """Generate a unique color for a domain path.

    The second-level segment (the actual branching point) gets spread
    across the full color wheel using golden angle spacing. Deeper
    segments shift the hue slightly from their parent.
    """
    parts = path.split("/")

    if len(parts) <= 1:
        base_hue = REGION_BASE_HUE.get(parts[0], DEFAULT_HUE)
        return _hsl_to_hex(base_hue, 70, 50)

    # Hash the second-level path for the base hue, spread across full spectrum
    key = "/".join(parts[:2])
    h = 0
    for c in key:
        h = h * 31 + ord(c)
    hue = (h * 137.508) % 360

    # Deeper levels shift hue ±25 from parent
    for i, part in enumerate(parts[2:], 2):
        sh = 0
        for c in part:
            sh = sh * 31 + ord(c)
        hue = (hue + (sh % 50) - 25) % 360

    # Depth affects saturation and lightness
    saturation = max(50, 75 - len(parts) * 3)
    lightness = min(60, 48 + len(parts) * 3)

    return _hsl_to_hex(hue, saturation, lightness)


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
def get_graph_data():
    """Return graph data in cosmic_data_v4 format."""
    settings = get_settings()
    conn = get_connection(settings.db_path)

    # Get all domains with docs
    domains_raw = conn.execute(
        "SELECT id, path, parent_path, document_count, spec_version FROM domains WHERE document_count > 0 ORDER BY path"
    ).fetchall()
    domains = [{"id": r[0], "path": r[1], "parent_path": r[2], "doc_count": r[3], "spec_version": r[4]} for r in domains_raw]

    # Domain positions
    domain_positions = _layout_domains(domains)

    # Domain doc counts
    domain_doc_counts = {d["path"]: d["doc_count"] for d in domains}

    # Region colors — each domain gets a unique color from its path hash
    # The viz uses region_colors keyed by top-level region, but we also
    # provide per-domain colors so entities can blend
    region_colors = {}
    for d in domains:
        region = d["path"].split("/")[0]
        if region not in region_colors:
            region_colors[region] = _domain_color(region)
        # Also add per-domain colors (viz will use these if available)
        region_colors[d["path"]] = _domain_color(d["path"])

    # Subdomains (3+ levels deep)
    subdomains = [d["path"] for d in domains if d["path"].count("/") >= 2]

    # Entities with domain weights
    entities_raw = conn.execute("""
        SELECT e.id, e.canonical_name, e.type,
               (SELECT COUNT(*) FROM entity_sources es WHERE es.entity_id = e.id) as source_count
        FROM entities e
        ORDER BY source_count DESC
    """).fetchall()

    entities = []
    for e in entities_raw:
        # Get domain weights for this entity
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
            "entityId": e[0],
            "name": e[1],
            "type": e[2],
            "videoCount": e[3],
            "domainWeights": domain_weights,
        })

    # Trade routes — domains that share entities, weighted by count of shared entity mentions
    shared = conn.execute("""
        SELECT dd1.domain_path, dd2.domain_path, COUNT(*) as weight
        FROM entity_sources es1
        JOIN entity_sources es2 ON es1.entity_id = es2.entity_id AND es1.document_id != es2.document_id
        JOIN document_domains dd1 ON es1.document_id = dd1.document_id
        JOIN document_domains dd2 ON es2.document_id = dd2.document_id
        WHERE dd1.domain_path < dd2.domain_path
        GROUP BY dd1.domain_path, dd2.domain_path
    """).fetchall()

    trade_routes = [
        {"source": r[0], "target": r[1], "weight": r[2]}
        for r in shared
    ]

    # Documents (for comet animations)
    docs_raw = conn.execute("""
        SELECT d.id, d.title, GROUP_CONCAT(dd.domain_path) as domains
        FROM documents d
        LEFT JOIN document_domains dd ON d.id = dd.document_id
        GROUP BY d.id
        ORDER BY d.created_at DESC
        LIMIT 50
    """).fetchall()

    videos = [
        {
            "id": r[0],
            "title": r[1],
            "domains": r[2].split(",") if r[2] else [],
            "primary": r[2].split(",")[0] if r[2] else None,
        }
        for r in docs_raw
    ]

    conn.close()

    return {
        "domain_positions": domain_positions,
        "domain_video_counts": domain_doc_counts,
        "region_colors": region_colors,
        "subdomains": subdomains,
        "videos": videos,
        "entities": entities,
        "v3_entities": [],  # compat field
        "trade_routes": trade_routes,
    }
