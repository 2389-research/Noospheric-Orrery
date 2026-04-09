# ABOUTME: Extract entities from document chunks using an LLM and an extraction spec.
# ABOUTME: Uses tool use for guaranteed valid JSON. Takes a Relay instance.

from orrery_relay import Relay

EXTRACTION_PROMPT = """You are an entity extraction system. Follow the extraction spec below exactly.

EXTRACTION SPEC:
{spec}

TEXT TO EXTRACT FROM:
{chunk_text}

Extract all entities mentioned in the text according to the spec. Only extract entities explicitly present — do not hallucinate or infer. Normalize names: lowercase, strip extra whitespace."""

ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Entity name, lowercase, stripped"},
                    "type": {"type": "string", "description": "Entity type from the spec"},
                },
                "required": ["name", "type"],
            },
        },
    },
    "required": ["entities"],
}


async def extract_entities_from_chunk(relay: Relay, chunk_text: str, spec: str, model: str) -> list[dict]:
    result = await relay.complete_structured(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(spec=spec, chunk_text=chunk_text)}],
        schema=ENTITY_SCHEMA,
        tool_name="extract_entities",
        tool_description="Extract named entities from the text according to the extraction spec",
    )
    return result.get("entities", [])


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
