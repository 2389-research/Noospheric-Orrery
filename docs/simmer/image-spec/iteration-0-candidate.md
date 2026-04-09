# Image Extraction Spec — General Seed

For each image, extract the following structured information.

## Entity Types

- **Subject** — the primary focus of the image (a person, animal, object, scene, building, artwork, etc.)
- **Object** — identifiable items visible (tools, products, vehicles, furniture, clothing, food, instruments, etc.)
- **Person** — anyone visible or identifiable by name
- **Text** — any readable text in the image (signs, labels, watermarks, captions, handwriting, screens)
- **Setting** — the environment or location (indoor, outdoor, studio, natural, urban, specific place if identifiable)
- **Style** — visual medium or technique (photograph, painting, illustration, diagram, screenshot, macro, aerial, etc.)
- **Material** — visible materials, textures, or surfaces (metal, wood, fabric, glass, stone, water, etc.)

## Extraction Rules

- Extract ONLY what is actually visible in the image — do not infer or hallucinate
- Normalize entity names to lowercase
- One entity per distinct thing — don't merge ("red car" and "blue car" are two entities)
- For people: use visible name if shown, otherwise describe role ("man in suit", "child")
- For text: transcribe exactly what's readable
- Be specific when possible ("golden retriever" not just "dog", "cherry blossom tree" not just "tree")

## Output Format

Return valid JSON:
```json
{
  "entities": [
    {"name": "entity name lowercase", "type": "EntityType"}
  ],
  "description": "2-3 sentence description of what the image shows. Be specific and factual. Focus on what would help someone searching for this image.",
  "tags": ["searchable", "tags", "for", "discovery"]
}
```

## Description Guidelines

- Lead with the main subject
- Include key visual details (colors, composition, mood)
- Mention the context or setting
- Write for searchability — someone looking for this content should find it
- Do NOT include subjective quality judgments ("beautiful", "amazing")
