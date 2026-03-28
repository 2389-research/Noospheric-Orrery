import json
from anthropic import AsyncAnthropic

CLASSIFICATION_PROMPT = """You are a document classifier for a knowledge graph system. Given a document excerpt and existing domain taxonomy, classify the document.

Existing taxonomy:
{taxonomy}

Document:
{excerpt}

Respond with JSON only:
{{
    "primary_domain": "region/parent/subdomain",
    "secondary_domains": ["other/domains"],
    "new_domains": ["proposed/new/domains"],
    "confidence": 0.0-1.0
}}

Rules:
- Use existing domains when they fit (exact path match)
- Propose new domains only when nothing in the taxonomy covers the content
- Domain paths are hierarchical: region/parent/subdomain
- A document can have 1 primary and 0-3 secondary domains
"""

async def classify_document(
    client: AsyncAnthropic,
    title: str,
    excerpt: str,
    existing_taxonomy: list[str],
    model: str,
) -> dict:
    taxonomy_str = "\n".join(f"  - {d}" for d in existing_taxonomy) if existing_taxonomy else "  (empty — propose new domains)"

    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": CLASSIFICATION_PROMPT.format(taxonomy=taxonomy_str, excerpt=excerpt)}],
    )

    text = response.content[0].text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)
