# ABOUTME: Classify documents into domains using an LLM.
# ABOUTME: Uses tool use for guaranteed valid JSON. Takes a Relay instance.

from orrery_relay import Relay

CLASSIFICATION_PROMPT = """You are a document classifier for a knowledge graph system. Given a document excerpt and existing domain taxonomy, classify the document.

Existing taxonomy:
{taxonomy}

Document:
{excerpt}

Rules:
- Use existing domains when they fit
- You CAN and SHOULD create new domain paths that don't exist in the taxonomy if the document covers a topic not well represented by existing domains
- Domain paths are hierarchical: region/parent/subdomain (e.g., business/technology/ai, business/legal/contracts)
- A document can have 1 primary and 0-3 secondary domains
- Be specific — prefer "region/parent/specific_topic" over just "region/parent"
- New domains are automatically added to the taxonomy, so don't hesitate to propose them
"""

CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_domain": {
            "type": "string",
            "description": "Primary domain path (region/parent/subdomain)",
        },
        "secondary_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "0-3 secondary domain paths",
        },
        "confidence": {
            "type": "number",
            "description": "Classification confidence 0.0-1.0",
        },
    },
    "required": ["primary_domain", "secondary_domains", "confidence"],
}


async def classify_document(
    relay: Relay,
    title: str,
    excerpt: str,
    existing_taxonomy: list[str],
    model: str,
) -> dict:
    taxonomy_str = "\n".join(f"  - {d}" for d in existing_taxonomy) if existing_taxonomy else "  (empty — propose new domains)"

    return await relay.complete_structured(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": CLASSIFICATION_PROMPT.format(taxonomy=taxonomy_str, excerpt=excerpt)}],
        schema=CLASSIFICATION_SCHEMA,
        tool_name="classify_document",
        tool_description="Classify a document into domain paths for the knowledge graph",
    )
