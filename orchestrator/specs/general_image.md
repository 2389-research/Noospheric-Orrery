## Entity Types

- Subject — the primary focus of the image. For representations (paintings, miniatures, sculptures, screenshots), the subject is the representation itself.
- Object — identifiable items visible (tools, products, vehicles, furniture, clothing, food, instruments, etc.)
- Person — anyone visible or identifiable
- Text — any readable text (signs, labels, watermarks, captions, handwriting, screens)
- Setting — the environment or location depicted
- Material — visible materials, textures, or surfaces (metal, wood, fabric, glass, stone, water, etc.)
- Color — 2-4 most prominent colors (use descriptive names: "cobalt blue", "burnished gold")

## Rules

- Extract ONLY what is actually visible — do not infer or hallucinate
- Be specific ("cherry blossom tree" not "tree", "espresso machine" not "machine")
- For groups: extract the group AND notable individuals if distinguishable
- Names must be lowercase

## Output

For this image extract:
1. All entities (name + type from above)
2. A 2-3 sentence description: medium + subject, then visual details, then context
3. Searchable tags (categories, mood, use-case)
