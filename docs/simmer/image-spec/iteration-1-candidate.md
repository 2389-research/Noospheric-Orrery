# Image Extraction Spec — General Seed

For each image, extract structured information about what is visible. Distinguish between what the image SHOWS (the visual content) and what the image IS (the medium and context).

## Entity Types

- **Subject** — the primary focus of the image. If the image is of a representation (a painting, miniature, sculpture, screenshot), the subject is the representation itself, not what it depicts.
- **Object** — identifiable items visible (tools, products, vehicles, furniture, clothing, food, instruments, etc.)
- **Person** — anyone visible or identifiable
- **Text** — any readable text (signs, labels, watermarks, captions, handwriting, screens)
- **Setting** — the environment or location depicted or where the photo was taken
- **Material** — visible materials, textures, or surfaces (metal, wood, fabric, glass, stone, water, paint, resin, etc.)
- **Color** — dominant or notable colors in the image (use descriptive names: "cobalt blue", "burnished gold", not just "blue")

## Image Context

In addition to entities, note:
- **medium**: What is this image? (photograph, painting, illustration, diagram, screenshot, render, etc.)
- **shot_type**: How was it captured? (close-up, wide angle, macro, aerial, product shot, portrait, candid, etc.)
- **representation_layer**: If the image shows an artwork, model, miniature, or reproduction — note what the depicted object IS (e.g., "painted miniature of a warrior") separately from the surface-level content (e.g., "warrior with sword"). If the image is a direct photograph of a real scene, this is "direct".

## Extraction Rules

- Extract ONLY what is actually visible — do not infer or hallucinate
- Normalize entity names to lowercase
- One entity per distinct thing
- For people: use visible name if shown, otherwise describe role ("man in suit", "child")
- For text: transcribe exactly what's readable
- Be specific when possible ("cherry blossom tree" not "tree", "banksia flower" not "flower")
- For colors: extract the 2-4 most prominent or notable colors as entities

## Output Format

Return valid JSON:
```json
{
  "entities": [
    {"name": "entity name lowercase", "type": "EntityType"}
  ],
  "description": "2-3 sentence description. Lead with the main subject. Include key visual details (colors, composition, mood, medium). Mention context or setting. Write for searchability.",
  "tags": ["searchable", "tags", "for", "discovery"],
  "shot_type": "product shot | close-up | wide angle | macro | portrait | candid | aerial | other"
}
```

## Description Guidelines

- Lead with what the image IS (medium + subject), not just what it depicts
  - Good: "A product photograph of a hand-painted miniature steampunk airship..."
  - Bad: "A steampunk airship..."
- Include 2-4 key visual details (colors, textures, lighting, composition)
- Mention the setting or context
- Write for searchability — someone looking for this content should find it
- Do NOT include subjective quality judgments ("beautiful", "amazing")
