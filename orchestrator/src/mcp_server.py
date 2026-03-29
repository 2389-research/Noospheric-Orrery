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

import json
import sys
import asyncio
import httpx

# MCP server reads from stdin, writes to stdout
ORCHESTRATOR_URL = "http://localhost:8100"


async def call_api(path: str, method: str = "GET") -> dict:
    async with httpx.AsyncClient() as client:
        if method == "GET":
            resp = await client.get(f"{ORCHESTRATOR_URL}{path}", timeout=30)
        else:
            resp = await client.post(f"{ORCHESTRATOR_URL}{path}", timeout=30)
        return resp.json()


def make_tool_list():
    return [
        {
            "name": "search_knowledge_graph",
            "description": "Search the knowledge graph for entities and document chunks matching a query. Returns ranked entities with types and relevant document excerpts. The galaxy visualization will light up showing where the results live in the graph.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query — can be a concept, person, organization, or any topic"},
                    "top_k": {"type": "integer", "description": "Number of results to return", "default": 15},
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_entity",
            "description": "Look up a specific entity by name. Returns its type, source documents, merge history, and co-occurring entities.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Entity name (case-insensitive)"},
                },
                "required": ["name"],
            },
        },
        {
            "name": "get_document",
            "description": "Read a document with entity highlights. Returns the document text segmented with entity annotations.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Document title (partial match)"},
                },
                "required": ["title"],
            },
        },
        {
            "name": "list_domains",
            "description": "List all domains in the knowledge graph taxonomy with document counts and spec status.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_entities",
            "description": "Browse entities, optionally filtered by type.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Entity type filter (Person, Organization, Product, Technology, Event, Concept, Location, Domain, etc.)"},
                    "limit": {"type": "integer", "description": "Max results", "default": 20},
                },
            },
        },
    ]


async def handle_tool_call(name: str, arguments: dict) -> str:
    """Execute a tool and return the result as text."""
    try:
        if name == "search_knowledge_graph":
            query = arguments["query"]
            top_k = arguments.get("top_k", 15)
            result = await call_api(f"/search?q={query}&top_k={top_k}")
            # Format for the agent
            lines = [f"Search: \"{result['query']}\" — {result['total_entities']} entities, {result['total_chunks']} chunks\n"]
            lines.append("Top entities:")
            for e in result["entities"][:10]:
                lines.append(f"  • {e['name']} ({e['type']}) — {e['source_count']} docs, score {e['score']:.4f}")
            lines.append("\nRelevant excerpts:")
            for c in result["chunks"][:5]:
                lines.append(f"  [{c['document_title']}]: {c['text'][:200]}")
            return "\n".join(lines)

        elif name == "get_entity":
            entity_name = arguments["name"]
            # Find entity by name
            entities = await call_api(f"/entities?limit=500")
            match = next((e for e in entities if e["canonical_name"].lower() == entity_name.lower()), None)
            if not match:
                return f"Entity '{entity_name}' not found"
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

        elif name == "get_document":
            title = arguments["title"]
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

        elif name == "list_domains":
            domains = await call_api("/domains")
            lines = ["Domain Taxonomy:\n"]
            for d in domains:
                spec = f"v{d['spec_version']}" if d.get("spec_version") else "no spec"
                lines.append(f"  {d['path']} — {d['document_count']} docs, {spec}")
            return "\n".join(lines)

        elif name == "list_entities":
            etype = arguments.get("type", "")
            limit = arguments.get("limit", 20)
            path = f"/entities?limit={limit}"
            if etype:
                path += f"&type={etype}"
            entities = await call_api(path)
            lines = [f"Entities ({len(entities)}):\n"]
            for e in entities:
                lines.append(f"  • {e['canonical_name']} ({e['type']}) — {e['source_count']} sources")
            return "\n".join(lines)

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        return f"Error: {str(e)}"


async def run_mcp_server():
    """Run the MCP server on stdio."""
    # Simple MCP protocol implementation
    # Reads JSON-RPC from stdin, writes responses to stdout

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

    async def send(msg):
        data = json.dumps(msg)
        header = f"Content-Length: {len(data)}\r\n\r\n"
        writer.write(header.encode() + data.encode())
        await writer.drain()

    while True:
        # Read header
        header_line = await reader.readline()
        if not header_line:
            break
        header = header_line.decode().strip()
        if header.startswith("Content-Length:"):
            content_length = int(header.split(":")[1].strip())
            await reader.readline()  # empty line
            body = await reader.readexactly(content_length)
            msg = json.loads(body)

            if msg.get("method") == "initialize":
                await send({
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "noospheric-orrery", "version": "1.0.0"},
                    },
                })
            elif msg.get("method") == "tools/list":
                await send({
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": {"tools": make_tool_list()},
                })
            elif msg.get("method") == "tools/call":
                tool_name = msg["params"]["name"]
                tool_args = msg["params"].get("arguments", {})
                result_text = await handle_tool_call(tool_name, tool_args)
                await send({
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": {
                        "content": [{"type": "text", "text": result_text}],
                    },
                })
            elif msg.get("method") == "notifications/initialized":
                pass  # ack
            else:
                await send({
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "error": {"code": -32601, "message": f"Method not found: {msg.get('method')}"},
                })


if __name__ == "__main__":
    asyncio.run(run_mcp_server())
