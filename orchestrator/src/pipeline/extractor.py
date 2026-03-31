# ABOUTME: Extract entities from document chunks using an LLM and an extraction spec.
# ABOUTME: Takes a Relay instance and returns deduplicated entity lists.

import json
from orrery_relay import Relay

EXTRACTION_WRAPPER = """You are an entity extraction system. Follow the extraction spec below exactly.

EXTRACTION SPEC:
{spec}

TEXT TO EXTRACT FROM:
{chunk_text}

Respond with JSON only:
{{
    "entities": [
        {{"name": "entity name", "type": "EntityType"}}
    ]
}}

Rules:
- Only extract entities explicitly mentioned in the text
- Do not hallucinate or infer entities not present
- Use the entity types defined in the spec
- Normalize names: lowercase, strip extra whitespace
"""

async def extract_entities_from_chunk(relay: Relay, chunk_text: str, spec: str, model: str) -> list[dict]:
    response = await relay.complete(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": EXTRACTION_WRAPPER.format(spec=spec, chunk_text=chunk_text)}],
    )
    text = response.text
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text).get("entities", [])

async def extract_document(relay: Relay, chunks: list[dict], spec: str, model: str) -> list[dict]:
    all_entities = []
    seen = set()
    for chunk in chunks:
        entities = await extract_entities_from_chunk(relay=relay, chunk_text=chunk["text"], spec=spec, model=model)
        for entity in entities:
            key = (entity["name"].lower().strip(), entity["type"])
            if key not in seen:
                seen.add(key)
                entity["chunk_id"] = chunk.get("id")
                all_entities.append(entity)
    return all_entities
