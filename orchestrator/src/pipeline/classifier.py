# ABOUTME: Classify documents into domains using an LLM.
# ABOUTME: Takes a Relay instance and returns primary/secondary domain paths.

import json
from orrery_relay import Relay

CLASSIFICATION_PROMPT = """You are a document classifier for a knowledge graph system. Given a document excerpt and existing domain taxonomy, classify the document.

Existing taxonomy:
{taxonomy}

Document:
{excerpt}

Respond with JSON only:
{{
    "primary_domain": "region/parent/subdomain",
    "secondary_domains": ["other/domains"],
    "confidence": 0.0-1.0
}}

Rules:
- Use existing domains when they fit
- You CAN and SHOULD create new domain paths that don't exist in the taxonomy if the document covers a topic not well represented by existing domains
- Domain paths are hierarchical: region/parent/subdomain (e.g., business/technology/ai, business/legal/contracts)
- A document can have 1 primary and 0-3 secondary domains
- Be specific — prefer "region/parent/specific_topic" over just "region/parent" (e.g., "business/fundraising/seed_round", "science/biology/genetics", "hobby/miniature_painting/techniques")
- New domains are automatically added to the taxonomy, so don't hesitate to propose them
"""

async def classify_document(
    relay: Relay,
    title: str,
    excerpt: str,
    existing_taxonomy: list[str],
    model: str,
) -> dict:
    taxonomy_str = "\n".join(f"  - {d}" for d in existing_taxonomy) if existing_taxonomy else "  (empty — propose new domains)"

    response = await relay.complete(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": CLASSIFICATION_PROMPT.format(taxonomy=taxonomy_str, excerpt=excerpt)}],
    )

    text = response.text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)
