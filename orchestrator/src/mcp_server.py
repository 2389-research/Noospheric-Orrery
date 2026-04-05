"""MCP server exposing the Noospheric Orrery knowledge graph as tools.

Run with: python -m src.mcp_server

Tools:
- search_knowledge_graph(query) — semantic search over entities and chunks
- get_entity(name) — look up entity details, sources, co-occurrences
- get_document(title) — read a document with entity highlights
- list_domains() — see the domain taxonomy
- list_entities(type, limit) — browse entities by type

Each tool call that touches the graph triggers a WebSocket broadcast,
causing the galaxy visualization to light up in real time.
"""

import os
import httpx
from mcp.server.fastmcp import FastMCP

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8100")

mcp = FastMCP("noospheric-orrery")


async def call_api(path: str, method: str = "GET") -> dict:
    async with httpx.AsyncClient() as client:
        if method == "GET":
            resp = await client.get(f"{ORCHESTRATOR_URL}{path}", timeout=30)
        else:
            resp = await client.post(f"{ORCHESTRATOR_URL}{path}", timeout=30)
        return resp.json()


@mcp.tool()
async def search_knowledge_graph(query: str, top_k: int = 15) -> str:
    """Search the knowledge graph for entities and document chunks matching a query.
    Returns ranked entities with types and relevant document excerpts.
    The galaxy visualization will light up showing where the results live in the graph."""
    result = await call_api(f"/search?q={query}&top_k={top_k}&expand=true")
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
        lines.append(f"\nOften appears with:")
        for c in coocs[:8]:
            lines.append(f"  • {c['canonical_name']} ({c['type']}) — weight {c['weight']}")
    return "\n".join(lines)


@mcp.tool()
async def get_document(title: str) -> str:
    """Read a document with entity highlights. Returns the document text segmented with entity annotations."""
    docs = await call_api("/documents")
    match = next((d for d in docs if title.lower() in d["title"].lower()), None)
    if not match:
        return f"Document matching '{title}' not found"
    reader = await call_api(f"/documents/{match['id']}/reader")
    lines = [f"Document: {reader['document']['title']}"]
    lines.append(f"Entities: {len(reader['entities'])} | Mentions: {reader['total_mentions']}")
    lines.append(f"Domains: {', '.join(reader['document']['domains'])}")
    lines.append(f"\n--- Content ---")
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


if __name__ == "__main__":
    mcp.run()
