# Image Extraction Spec — General Seed

For each image, extract structured information about what is visible. Distinguish between what the image SHOWS (the visual content) and what the image IS (the medium and context).

## Entity Types

- **Subject** — the primary focus of the image. If the image shows a representation (a painting, miniature, sculpture, screenshot), the subject is the representation itself, not what it depicts.
- **Object** — identifiable items visible (tools, products, vehicles, furniture, clothing, food, instruments, etc.)
- **Person** — anyone visible or identifiable
- **Text** — any readable text (signs, labels, watermarks, captions, handwriting, screens)
- **Setting** — the environment or location depicted or where the photo was taken
- **Material** — visible materials, textures, or surfaces (metal, wood, fabric, glass, stone, water, paint, resin, etc.)
- **Color** — dominant or notable colors (use descriptive names: "cobalt blue", "burnished gold", not just "blue"). Extract 2-4 most prominent.

## Extraction Rules

- Extract ONLY what is actually visible — do not infer or hallucinate
- Normalize entity names to lowercase
- One entity per distinct thing
- For people: use visible name if shown, otherwise describe role ("man in suit", "child")
- For text: transcribe exactly what's readable
- Be specific when possible ("cherry blossom tree" not "tree", "banksia flower" not "flower")

## Output Format

Return valid JSON:
```json
{
  "entities": [
    {"name": "entity name lowercase", "type": "EntityType"}
  ],
  "description": "2-3 sentence description. See guidelines below.",
  "tags": ["searchable", "tags", "for", "discovery"],
  "medium": "photograph | painting | illustration | diagram | screenshot | render | other",
  "shot_type": "product shot | close-up | wide angle | macro | portrait | candid | aerial | other",
  "representation": "direct | description of what the depicted object is (e.g., 'painted miniature', 'oil painting', 'architectural model')"
}
```

## Description Guidelines

- **First sentence**: What the image IS — medium + primary subject.
  - "A macro photograph of a banksia flower head..."
  - "A product photograph of a hand-painted miniature steampunk airship..."
  - "A travel photograph of the Great Wall of China..."
- **Second sentence**: Key visual details — colors, textures, lighting, composition, notable features.
- **Third sentence** (optional): Context, setting, or additional details relevant to searchability.
- Do NOT include subjective quality judgments ("beautiful", "stunning").
- Write for search — someone looking for this content should find it from the description.
