# ABOUTME: Stage 0: Query expansion via Haiku.
# ABOUTME: Expands a search query into multiple sub-queries using an LLM.

import json
from orrery_relay import Relay


async def expand_query(
    relay: Relay,
    query: str,
    max_sub_queries: int = 5,
) -> list[str]:
    """Expand a query into multiple sub-queries using Haiku."""
    response = await relay.complete(
        model="claude-haiku-4-5",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": f"""Given this search query, generate {max_sub_queries} sub-queries that would help find all relevant information. Include:
- The original query (cleaned up)
- Synonym variations
- Related concepts
- More specific versions of vague terms

Query: {query}

Return as a JSON array of strings only. No explanation.""",
        }],
    )

    text = response.text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        sub_queries = json.loads(text)
        if isinstance(sub_queries, list):
            return sub_queries[:max_sub_queries]
    except json.JSONDecodeError:
        pass

    return [query]
