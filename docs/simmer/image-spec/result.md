# Image Extraction Spec — General Seed

For each image, extract structured information about what is visible. Distinguish between what the image SHOWS (the visual content) and what the image IS (the medium and context).

## Entity Types

- **Subject** — the primary focus of the image. For representations (paintings, miniatures, sculptures, screenshots), the subject is the representation itself. For multi-subject images, extract each distinct subject separately.
- **Object** — identifiable items visible (tools, products, vehicles, furniture, clothing, food, instruments, etc.)
- **Person** — anyone visible or identifiable
- **Text** — any readable text (signs, labels, watermarks, captions, handwriting, screens)
- **Setting** — the environment or location depicted or where the image was taken
- **Material** — visible materials, textures, or surfaces (metal, wood, fabric, glass, stone, water, paint, resin, etc.)
- **Color** — dominant or notable colors (use descriptive names: "cobalt blue", "burnished gold", not just "blue"). Extract 2-4 most prominent.

## Extraction Rules

- Extract ONLY what is actually visible — do not infer or hallucinate
- Normalize entity names to lowercase
- One entity per distinct thing
- For people: use visible name if shown, otherwise describe role ("man in suit", "child")
- For text: transcribe exactly what's readable
- Be specific when possible ("cherry blossom tree" not "tree", "banksia flower" not "flower")
- For groups: extract the group as one entity AND notable individual items if distinguishable

## Output Format

Return valid JSON:
```json
{
  "entities": [
    {"name": "entity name lowercase", "type": "EntityType"}
  ],
  "description": "2-3 sentence description. See guidelines below.",
  "tags": ["category", "subject", "mood", "technique", "use-case"],
  "medium": "photograph | painting | illustration | diagram | screenshot | render | other",
  "shot_type": "product shot | close-up | wide angle | macro | portrait | candid | aerial | flat lay | other",
  "representation": "direct | painted miniature | oil painting | digital illustration | scale model | sculpture | architectural model | other [describe]"
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

## Tag Guidelines

Tags should aid discovery beyond what entities and descriptions cover:
- Include broad categories ("nature", "architecture", "tabletop gaming")
- Include mood or atmosphere ("dramatic", "serene", "moody")
- Include potential use cases ("reference photo", "product photography", "texture reference")
- Do NOT just repeat entity names as tags — tags should add search surface
