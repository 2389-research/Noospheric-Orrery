# ABOUTME: Stage 0: Query expansion via Haiku.
# ABOUTME: Uses tool use for guaranteed valid JSON output.

from orrery_relay import Relay

EXPANSION_SCHEMA = {
    "type": "object",
    "properties": {
        "sub_queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Expanded search sub-queries",
        },
    },
    "required": ["sub_queries"],
}


async def expand_query(
    relay: Relay,
    query: str,
    max_sub_queries: int = 5,
) -> list[str]:
    """Expand a query into multiple sub-queries using Haiku."""
    result = await relay.complete_structured(
        model="claude-haiku-4-5",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": f"""Given this search query, generate {max_sub_queries} sub-queries that would help find all relevant information. Include:
- The original query (cleaned up)
- Synonym variations
- Related concepts
- More specific versions of vague terms

Query: {query}""",
        }],
        schema=EXPANSION_SCHEMA,
        tool_name="expand_query",
        tool_description="Generate search sub-queries to expand the original query",
    )
    return result.get("sub_queries", [query])[:max_sub_queries]
