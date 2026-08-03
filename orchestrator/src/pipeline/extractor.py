# ABOUTME: Extract entities from document chunks (text) and images using an LLM.
# ABOUTME: Uses tool use for guaranteed valid JSON. Takes a Relay instance.

from orrery_relay import Relay
from .section_splitter import SKIP_SECTIONS

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


async def extract_document_sectioned(
    relay: Relay, chunks: list[dict], section_specs: dict[str, str], model: str,
) -> list[dict]:
    all_entities = []
    seen = set()
    for chunk in chunks:
        if chunk.get("section") in SKIP_SECTIONS:
            continue
        spec = section_specs.get(chunk.get("section"), section_specs["default"])
        entities = await extract_entities_from_chunk(relay=relay, chunk_text=chunk["text"], spec=spec, model=model)
        for entity in entities:
            key = (entity["name"].lower().strip(), entity["type"])
            if key not in seen:
                seen.add(key)
                entity["chunk_id"] = chunk.get("id")
                all_entities.append(entity)
    return all_entities


# --- Image extraction ---

IMAGE_EXTRACTION_PROMPT = """You are a visual entity extraction system. Follow the extraction spec below exactly.

EXTRACTION SPEC:
{spec}

Look at this image and extract all entities, metadata, and descriptions according to the spec.
Only extract what is actually visible — do not hallucinate or infer things not shown.
Normalize names: lowercase, strip extra whitespace."""

IMAGE_ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Entity name, lowercase"},
                    "type": {"type": "string", "description": "Entity type from the spec"},
                },
                "required": ["name", "type"],
            },
        },
        "description": {
            "type": "string",
            "description": "2-3 sentences: first = medium + subject, second = visual details, third = context",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Searchable tags — categories, mood, use-case (not just entity name repeats)",
        },
        "medium": {
            "type": "string",
            "description": "photograph, painting, illustration, diagram, screenshot, render, or other",
        },
        "shot_type": {
            "type": "string",
            "description": "product shot, close-up, wide angle, macro, portrait, candid, aerial, flat lay, or other",
        },
        "representation": {
            "type": "string",
            "description": "direct (real scene) or what the depicted object is (painted miniature, oil painting, scale model, etc.)",
        },
    },
    "required": ["entities", "description", "tags"],
}


async def extract_entities_from_image(
    relay: Relay,
    image_base64: str,
    media_type: str,
    spec: str,
    model: str,
) -> dict:
    """Extract entities, description, and tags from an image using a visual spec."""
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_base64}},
        {"type": "text", "text": IMAGE_EXTRACTION_PROMPT.format(spec=spec)},
    ]
    return await relay.complete_structured(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": content}],
        schema=IMAGE_ENTITY_SCHEMA,
        tool_name="extract_image_entities",
        tool_description="Extract entities and metadata from an image",
    )
