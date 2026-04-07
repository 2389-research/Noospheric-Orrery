# Image Pipeline Design — Visual Documents in the Knowledge Graph

**Date:** 2026-04-06
**Status:** Draft

## Goal

Add image support to the Orrery pipeline. Images become first-class documents in the knowledge graph — classified into domains, tagged with entities/metadata via simmered visual specs, searchable alongside text, and visible in the galaxy viz.

## Architecture

### Upload & Storage

Images are uploaded the same way as text files. Supported formats: `.jpg`, `.png`, `.webp`, `.gif`. Stored in `documents/` with a `content_type` field (`text` or `image`) on the document record.

An image is treated as a single chunk — no splitting. The chunk's "text" field stores the file path or base64, and a `content_type` flag distinguishes it from text chunks.

Optional user-provided metadata (caption, tags, alt text) is stored as a separate field on the document and fed to the VLLM alongside the image.

### Classification

A vision-capable model (Sonnet, Gemma4 with vision, etc.) looks at the image and proposes domains, same as the text classifier. The classifier prompt is adapted for images:

- Text classifier: "Read this text and classify it into domains"
- Image classifier: "Look at this image and classify it into domains"

The domain taxonomy is shared — an image of a product meeting whiteboard lands in `business/strategy` alongside text meeting notes. Images don't get a separate taxonomy.

### Entity/Metadata Extraction

This is where images diverge from text. A text extraction spec says "find Person, Organization, Topic." An image extraction spec describes what to observe:

**General image spec (seed):**
```
For each image, extract:
- Subject: what is the primary subject (person, object, scene, diagram, etc.)
- Objects: named or identifiable objects, products, tools, brands visible
- People: anyone identifiable or described
- Text: any text visible in the image (signs, labels, screens, documents)
- Setting: indoor/outdoor, location type, context
- Style: photograph, screenshot, diagram, illustration, painting, etc.
- Description: 2-3 sentence description of what the image shows

Output as JSON: {"entities": [...], "description": "...", "tags": [...]}
```

The VLLM reads the image + spec directly. No intermediate text step — the model sees the actual pixels.

### Image-Specific Simmering

Images get their own general spec (separate from text). The simmering pattern is identical:

**Phase 1 — Golden Set:** VLLM looks at 10 sample images, builds a reference list of what's interesting. Judges verify against the images.

**Phase 2 — Extraction Spec:** Iteratively refine the visual extraction spec. The evaluator runs the VLLM with the candidate spec against sample images, diffs results against the golden set, judges read the raw outputs.

**Domain-specific visual specs:** Once 20 images cluster in a domain (e.g., `hobbies/miniature-painting`), a domain visual spec is simmered. For miniature painting: "identify the model/miniature, painting techniques visible (layering, wet blending, OSL), paint colors, base style, scale." For architecture: "identify building style, materials, era, notable features."

The threshold and trigger logic is the same as text — just a separate spec lineage for images.

### Embeddings & Search

Each image produces two embeddings:

1. **Image embedding** — from the raw image pixels
   - Cloud: Vertex AI multimodal embedding
   - Local: SigLIP (CLIP-family, produces embeddings in shared vision-language space)

2. **Text embedding** — from the extracted description + entity names
   - Same sentence-transformers / Vertex AI path as text documents

**Search approach:**

The text embedding from image descriptions goes into the same FAISS index as text documents. This means a text query like "miniature painting techniques" finds both text docs about painting AND images showing painting techniques.

For the combined index:
- Over-return results (e.g., top 50 instead of top 20)
- Post-filter by `content_type` if the user wants text-only or image-only
- For image results, optionally fuse the image embedding score with the text embedding score for a combined relevance score

No separate image-only index needed initially. The combined index with type filtering is simpler and lets cross-modal search work naturally.

### Graph Representation

In the galaxy viz, image-sourced entities appear the same as text-sourced entities. The document node has a visual indicator (thumbnail or icon) showing it's an image.

Co-occurrence edges work the same — entities extracted from the same image are co-occurring. An image of "Harper Reed at TechCrunch Disrupt" creates edges between Harper Reed, TechCrunch Disrupt, and any other entities visible.

## Schema Changes

```sql
-- Add content_type to documents
ALTER TABLE documents ADD COLUMN content_type TEXT DEFAULT 'text';
-- 'text' or 'image'

-- Add image_path to chunks (for image chunks, points to the file)
ALTER TABLE chunks ADD COLUMN image_path TEXT;

-- Spec lineage: image specs are separate from text specs
-- Existing specs table works — add a media_type field
ALTER TABLE specs ADD COLUMN media_type TEXT DEFAULT 'text';
-- 'text' or 'image'
```

## Pipeline Changes

| Component | Change |
|-----------|--------|
| `ingest.py` | Detect image files, store with `content_type='image'`, create single chunk |
| `classifier.py` | Vision-capable model call when `content_type='image'` |
| `extractor.py` | Vision-capable model call with image + spec |
| `evaluate_spec.py` | Pass image to VLLM instead of text chunks |
| `simmer_general.py` | Separate image spec lineage, image-specific seed |
| `search.py` | Combined index, type filtering |
| Frontend | Image upload support, thumbnail display in entity/doc views |
| `file-upload.tsx` | Accept image file extensions |

## What Stays The Same

- Domain taxonomy — shared across text and images
- Entity normalization — same dedup pipeline
- Co-occurrence computation — same logic
- Galaxy viz — entities are entities regardless of source
- MCP server — agents query the same way, images are just documents
- Simmer-sdk — same `refine()` loop, just with vision-capable models

## Model Requirements

| Tier | Classification | Extraction | Embedding |
|------|---------------|------------|-----------|
| Cloud | Sonnet 4.6 (vision) | Haiku 4.5 (vision) | Vertex AI multimodal |
| Local | gemma4:26b (vision) | gemma4:e4b (vision) | SigLIP |

Both Sonnet and Gemma4 support vision natively — images are passed as base64 in the message content.

## Open Questions

1. **Image preprocessing** — should we resize/compress before sending to VLLM? Large images waste tokens. A standard max dimension (e.g., 1024px) would reduce cost.
2. **Batch upload UX** — drag-and-drop a folder of images. Progress indicator per image.
3. **Thumbnail generation** — store a small thumbnail for the UI, or generate on-the-fly?
4. **Video frames** — future extension: extract key frames from video, treat each as an image document.
5. **OCR fallback** — for images that are primarily text (screenshots, documents), should we OCR and treat as text + image hybrid?
