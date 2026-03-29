"""Stage 0: Query expansion via Haiku."""

import json
from anthropic import AnthropicBedrock


async def expand_query(
    query: str,
    aws_access_key: str,
    aws_secret_key: str,
    aws_region: str,
    max_sub_queries: int = 5,
) -> list[str]:
    """Expand a query into multiple sub-queries using Haiku."""
    client = AnthropicBedrock(
        aws_access_key=aws_access_key,
        aws_secret_key=aws_secret_key,
        aws_region=aws_region,
    )

    response = client.messages.create(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
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

    text = response.content[0].text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        sub_queries = json.loads(text)
        if isinstance(sub_queries, list):
            return sub_queries[:max_sub_queries]
    except json.JSONDecodeError:
        pass

    return [query]
