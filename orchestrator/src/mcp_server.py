"""MCP server exposing the Noospheric Orrery knowledge graph as tools.

Run with: python -m src.mcp_server

Tools — Session:
- list_noospheres() — see available workspaces
- select_noosphere(name_or_id) — set active workspace for subsequent calls

Tools — Search & Read:
- search_knowledge_graph(query, top_k, include_images) — semantic search over entities and chunks (optionally cross-modal image hits)
- search_images(query, top_k) — SigLIP cross-modal image search
- get_entity(name) — look up entity details, sources, co-occurrences
- get_document(title) — read a document with entity highlights (notes content_type for image docs)
- list_domains() — see the domain taxonomy
- list_entities(type, limit) — browse entities by type

Tools — Graph Traversal:
- get_neighborhood(entity_name, depth, max_nodes) — multi-hop neighborhood expansion
- get_shared_context(entity_a, entity_b) — shared docs, neighbors, domains between two entities
- find_paths(entity_a, entity_b, max_depth) — shortest path(s) through co-occurrence edges
- get_subgraph(entity_names, max_hops) — bounded subgraph around seed entities
- explore_domain(domain_path) — domain overview with top entities and related domains
"""

import os
import json
import httpx
from mcp.server.fastmcp import FastMCP
from urllib.parse import quote

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8100")

mcp = FastMCP("noospheric-orrery")

# Session-level workspace selection
_active_workspace: str | None = None


async def call_api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Call the orchestrator API. Returns the JSON body on success, or a
    {"detail": ...} dict on transport / status / decode errors so MCP tools
    can surface a readable message instead of crashing."""
    headers = {}
    if _active_workspace:
        headers["X-Workspace-Id"] = _active_workspace
    try:
        async with httpx.AsyncClient() as client:
            if method == "GET":
                resp = await client.get(f"{ORCHESTRATOR_URL}{path}", headers=headers, timeout=30)
            else:
                resp = await client.post(f"{ORCHESTRATOR_URL}{path}", headers=headers, json=body, timeout=30)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        return {"detail": f"API {e.response.status_code}: {e.response.text[:200]}"}
    except httpx.RequestError as e:
        return {"detail": f"Connection error: {e}"}
    except json.JSONDecodeError:
        return {"detail": "Invalid (non-JSON) response from orchestrator"}


# ── Session ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_noospheres() -> str:
    """List all available noospheres (workspaces). Use select_noosphere() to pick one before querying."""
    workspaces = await call_api("/workspaces")
    if isinstance(workspaces, dict) and "detail" in workspaces:
        return f"Error: {workspaces['detail']}"
    lines = ["Available noospheres:\n"]
    for ws in workspaces:
        active = " ← active" if _active_workspace == ws["id"] else ""
        lines.append(f"  • {ws['name']} (id: {ws['id']}){active}")
    if not _active_workspace:
        lines.append("\nNo noosphere selected — use select_noosphere() to pick one.")
    return "\n".join(lines)


@mcp.tool()
async def select_noosphere(name_or_id: str) -> str:
    """Select a noosphere (workspace) by name or ID. All subsequent tool calls will query this noosphere."""
    global _active_workspace
    workspaces = await call_api("/workspaces")
    if isinstance(workspaces, dict) and "detail" in workspaces:
        return f"Error: {workspaces['detail']}"
    match = next(
        (ws for ws in workspaces
         if ws["id"] == name_or_id or ws["name"].lower() == name_or_id.lower()),
        None,
    )
    if not match:
        names = ", ".join(ws["name"] for ws in workspaces)
        return f"No noosphere matching '{name_or_id}'. Available: {names}"
    _active_workspace = match["id"]
    stats = await call_api("/stats")
    return (
        f"Switched to noosphere: {match['name']} (id: {match['id']})\n"
        f"  {stats.get('document_count', 0)} documents, "
        f"{stats.get('entity_count', 0)} entities, "
        f"{stats.get('domain_count', 0)} domains"
    )


# ── Search & Read ───────────────────────────────────────────────────────────

@mcp.tool()
async def search_knowledge_graph(query: str, top_k: int = 15, include_images: bool = False) -> str:
    """Search the knowledge graph for entities and document chunks matching a query.
    Returns ranked entities with types and relevant document excerpts.
    Set include_images=True to also surface visually-matching image documents via SigLIP cross-modal search.
    The galaxy visualization will light up showing where the results live in the graph."""
    inc = "true" if include_images else "false"
    result = await call_api(f"/search?q={quote(query)}&top_k={top_k}&expand=true&include_images={inc}")
    if "detail" in result and "query" not in result:
        return f"Search error: {result['detail']}"
    lines = [f"Search: \"{result['query']}\" — {result['total_entities']} entities, {result['total_chunks']} chunks"]
    if result.get("sub_queries_used"):
        lines.append(f"Sub-queries: {', '.join(result['sub_queries_used'])}")
    lines.append("\nTop entities:")
    for e in result["entities"][:10]:
        paths = ",".join(e.get("paths", []))
        hits = e.get("appearances", 0)
        lines.append(f"  • {e['name']} ({e['type']}) — {e.get('source_count', 0)} docs, score {e['score']:.4f} [{hits} sub-query hits, via {paths}]")
    lines.append("\nRelevant excerpts:")
    for c in result["chunks"][:5]:
        overlap = c.get("entity_overlap", 0)
        matching = c.get("matching_entities", "")
        lines.append(f"  [{c['document_title']}] (entities:{overlap}): {c['text'][:200]}")
        if matching:
            lines.append(f"    entities in chunk: {matching}")
    images = result.get("images") or []
    if images:
        lines.append(f"\nImage matches ({len(images)}):")
        for img in images[:5]:
            lines.append(f"  [image:{img['document_id']}] {img['title']} (score {img.get('score', 0):.3f}) — {img.get('description', '')}")
    return "\n".join(lines)


@mcp.tool()
async def search_images(query: str, top_k: int = 10) -> str:
    """Cross-modal image search via SigLIP. Returns image documents whose visual content
    matches the text query — pictures of "miniature painting", "city street", "fish tank",
    etc., even when the query text doesn't appear in the image description.
    Falls back to sentence-transformer text similarity on descriptions if SigLIP is unavailable."""
    result = await call_api(f"/search?q={quote(query)}&top_k={top_k}&expand=false&include_images=true")
    if "detail" in result and "query" not in result:
        return f"Image search error: {result['detail']}"
    images = result.get("images") or []
    if not images:
        return f"No image documents matched \"{query}\"."
    lines = [f"Image search: \"{query}\" — {len(images)} matches"]
    for img in images:
        lines.append(f"  [image:{img['document_id']}] {img['title']} (score {img.get('score', 0):.3f})")
        desc = (img.get('description') or '').strip()
        if desc:
            lines.append(f"    {desc}")
    return "\n".join(lines)


@mcp.tool()
async def get_entity(name: str) -> str:
    """Look up a specific entity by name. Returns its type, source documents, merge history, and co-occurring entities."""
    entities = await call_api("/entities?limit=500")
    match = next((e for e in entities if e["canonical_name"].lower() == name.lower()), None)
    if not match:
        return f"Entity '{name}' not found"
    detail = await call_api(f"/entities/{match['id']}")
    coocs = await call_api(f"/entities/{match['id']}/cooccurrences")
    lines = [f"{detail['canonical_name']} ({detail['type']})"]
    lines.append(f"Sources: {len(detail['sources'])} mentions across {len(set(s['document_id'] for s in detail['sources']))} docs")
    if detail.get("merge_history"):
        lines.append(f"Also known as: {', '.join(detail['merge_history'])}")
    if coocs:
        lines.append("\nOften appears with:")
        for c in coocs[:8]:
            lines.append(f"  • {c['canonical_name']} ({c['type']}) — weight {c['weight']}")
    return "\n".join(lines)


@mcp.tool()
async def get_document(title: str) -> str:
    """Read a document with entity highlights. Returns the document text segmented with entity annotations.
    For image documents the body is the vision-model description, and the result notes the content_type
    so the agent knows to fetch the raw image via /images/{document_id} if needed."""
    docs = await call_api("/documents")
    match = next((d for d in docs if title.lower() in d["title"].lower()), None)
    if not match:
        return f"Document matching '{title}' not found"
    reader = await call_api(f"/documents/{match['id']}/reader")
    doc = reader["document"]
    content_type = doc.get("content_type") or match.get("content_type") or "text"
    lines = [f"Document: {doc['title']} ({content_type})"]
    if content_type == "image":
        lines.append(f"Image URL: /images/{doc['id']}")
    lines.append(f"Entities: {len(reader['entities'])} | Mentions: {reader['total_mentions']}")
    lines.append(f"Domains: {', '.join(doc['domains'])}")
    lines.append("\n--- Content ---")
    text = "".join(seg["text"] for seg in reader["segments"])
    lines.append(text[:2000])
    if len(text) > 2000:
        lines.append(f"\n... [{len(text) - 2000} more characters]")
    return "\n".join(lines)


@mcp.tool()
async def list_domains() -> str:
    """List all domains in the knowledge graph taxonomy with document counts and spec status."""
    domains = await call_api("/domains")
    lines = ["Domain Taxonomy:\n"]
    for d in domains:
        spec = f"v{d['spec_version']}" if d.get("spec_version") else "no spec"
        lines.append(f"  {d['path']} — {d['document_count']} docs, {spec}")
    return "\n".join(lines)


@mcp.tool()
async def list_entities(type: str = "", limit: int = 20) -> str:
    """Browse entities, optionally filtered by type (Person, Organization, Product, Technology, Event, Concept, Location, Domain, etc.)."""
    path = f"/entities?limit={limit}"
    if type:
        path += f"&type={type}"
    entities = await call_api(path)
    lines = [f"Entities ({len(entities)}):\n"]
    for e in entities:
        lines.append(f"  • {e['canonical_name']} ({e['type']}) — {e['source_count']} sources")
    return "\n".join(lines)


# ── Graph Traversal ─────────────────────────────────────────────────────────

@mcp.tool()
async def get_neighborhood(entity_name: str, depth: int = 1, max_nodes: int = 20) -> str:
    """Expand the neighborhood around an entity. Returns connected entities within N hops.
    Use depth=1 for immediate neighbors, depth=2 to see friends-of-friends.
    This is the primary graph exploration tool — start here after search."""
    result = await call_api(f"/graph/neighborhood/{quote(entity_name)}?depth={depth}&max_nodes={max_nodes}")
    if "detail" in result:
        return f"Error: {result['detail']}"
    seed = result["seed"]
    lines = [f"Neighborhood of {seed['name']} ({seed['type']}) — {result['node_count']} nodes, {result['edge_count']} edges, depth {result['depth']}"]
    # Group nodes by depth
    by_depth: dict[int, list] = {}
    for n in result["nodes"]:
        by_depth.setdefault(n["depth"], []).append(n)
    for d in sorted(by_depth.keys()):
        if d == 0:
            continue
        nodes = sorted(by_depth[d], key=lambda x: -x["source_count"])
        lines.append(f"\n  Hop {d}:")
        for n in nodes:
            lines.append(f"    • {n['name']} ({n['type']}) — {n['source_count']} docs")
    return "\n".join(lines)


@mcp.tool()
async def get_shared_context(entity_a: str, entity_b: str) -> str:
    """Find what two entities have in common: shared documents, shared neighbors, shared domains.
    Use this to understand WHY two entities are related or to discover non-obvious connections."""
    result = await call_api(f"/graph/shared-context/{quote(entity_a)}/{quote(entity_b)}")
    if "detail" in result:
        return f"Error: {result['detail']}"
    ea, eb = result["entity_a"], result["entity_b"]
    summary = result["summary"]
    lines = [f"Shared context: {ea['name']} ({ea['type']}) ↔ {eb['name']} ({eb['type']})"]
    if result["direct_weight"]:
        lines.append(f"  Direct co-occurrence weight: {result['direct_weight']}")
    lines.append(f"  {summary['docs_in_common']} shared documents, {summary['neighbors_in_common']} shared neighbors, {summary['domains_in_common']} shared domains")
    if result["shared_documents"]:
        lines.append("\n  Shared documents:")
        for doc in result["shared_documents"][:8]:
            lines.append(f"    • {doc['title']}")
    if result["shared_neighbors"]:
        lines.append("\n  Shared neighbors (entities connected to both):")
        for n in result["shared_neighbors"][:8]:
            lines.append(f"    • {n['name']} ({n['type']}) — weight to A: {n['weight_to_a']}, to B: {n['weight_to_b']}")
    if result["shared_domains"]:
        lines.append(f"\n  Shared domains: {', '.join(result['shared_domains'])}")
    return "\n".join(lines)


@mcp.tool()
async def find_paths(entity_a: str, entity_b: str, max_depth: int = 4) -> str:
    """Find shortest path(s) between two entities through co-occurrence edges.
    Shows HOW two entities connect through the graph — useful for discovering indirect relationships."""
    result = await call_api(f"/graph/paths/{quote(entity_a)}/{quote(entity_b)}?max_depth={max_depth}")
    if "detail" in result:
        return f"Error: {result['detail']}"
    ea, eb = result["entity_a"], result["entity_b"]
    lines = [f"Paths: {ea['name']} → {eb['name']} — {result['path_count']} path(s) found (searched up to depth {result['searched_depth']})"]
    if not result["paths"]:
        lines.append("  No path found within the search depth.")
    for i, path in enumerate(result["paths"]):
        chain = " → ".join(f"{n['name']} ({n['type']})" for n in path["nodes"])
        lines.append(f"\n  Path {i+1} (length {path['length']}): {chain}")
    return "\n".join(lines)


@mcp.tool()
async def get_subgraph(entity_names: list[str], max_hops: int = 1) -> str:
    """Get the subgraph connecting a set of entities. Given seed entities (from a search or exploration),
    returns all nodes and edges between them. Use this to understand how search results relate to each other."""
    result = await call_api("/graph/subgraph", method="POST", body={"entity_names": entity_names, "max_hops": max_hops})
    if "detail" in result:
        return f"Error: {result['detail']}"
    seed_names = [s["name"] for s in result["seeds"]]
    lines = [f"Subgraph around {len(result['seeds'])} seeds: {', '.join(seed_names)}"]
    lines.append(f"  {result['node_count']} nodes, {result['edge_count']} edges (max_hops={max_hops})")
    # Show seeds
    lines.append("\n  Seed entities:")
    for s in result["seeds"]:
        lines.append(f"    ★ {s['name']} ({s['type']})")
    # Show discovered (non-seed) nodes
    discovered = [n for n in result["nodes"] if not n.get("is_seed")]
    if discovered:
        lines.append(f"\n  Discovered entities ({len(discovered)}):")
        for n in discovered[:20]:
            lines.append(f"    • {n['name']} ({n['type']})")
    # Show strongest edges
    if result["edges"]:
        top_edges = sorted(result["edges"], key=lambda e: -e["weight"])[:10]
        lines.append("\n  Strongest connections:")
        # Build name lookup
        name_map = {n["id"]: n["name"] for n in result["nodes"]}
        for e in top_edges:
            lines.append(f"    {name_map.get(e['source'], '?')} ↔ {name_map.get(e['target'], '?')} (weight {e['weight']})")
    return "\n".join(lines)


@mcp.tool()
async def explore_domain(domain_path: str) -> str:
    """Overview of a domain: documents, top entities, entity type distribution, and related domains.
    Use this to understand what a domain contains before diving into individual entities."""
    result = await call_api(f"/graph/domain-overview/{quote(domain_path, safe='/')}")
    if "detail" in result:
        return f"Error: {result['detail']}"
    domain = result["domain"]
    lines = [f"Domain: {domain['path']} — {domain['document_count']} documents" +
             (f", spec v{domain['spec_version']}" if domain.get("spec_version") else ", no spec")]
    # Documents
    lines.append(f"\n  Documents ({len(result['documents'])}):")
    for doc in result["documents"]:
        lines.append(f"    • {doc['title']} ({doc['content_type']})")
    # Entity type distribution
    if result["entity_type_distribution"]:
        lines.append("\n  Entity types:")
        for etype, count in sorted(result["entity_type_distribution"].items(), key=lambda x: -x[1]):
            lines.append(f"    {etype}: {count}")
    # Top entities
    if result["top_entities"]:
        lines.append("\n  Top entities:")
        for e in result["top_entities"][:15]:
            lines.append(f"    • {e['name']} ({e['type']}) — in {e['doc_count']} docs")
    # Related domains
    if result["related_domains"]:
        lines.append("\n  Related domains:")
        for rd in result["related_domains"]:
            lines.append(f"    • {rd['path']} ({rd['shared_entities']} shared entities)")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
