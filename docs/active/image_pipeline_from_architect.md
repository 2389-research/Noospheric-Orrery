# Image Pipeline — Full Design

**Date:** 2026-04-06
**Status:** Draft

---

## Overview

Images become first-class documents in the Orrery knowledge graph. The pipeline extends the existing text pipeline with minimal changes — same ingest pattern, same graph, same galaxy viz — but routes images through specialist models at each stage.

---

## Core Principles

- Two specialist indexes, never unified
- Text quality is not sacrificed for cross-modal convenience
- Images follow the same orrery pattern as text: ingest → classify → extract → embed → index → simmer
- Combined search is deferred until there's a real use case for it

---

## Pipeline Stages

### 1. Ingest

Same entry point as text. Images uploaded via the existing file upload flow.

- Supported formats: `.jpg`, `.png`, `.webp`, `.gif`
- Stored in `documents/` with `content_type: 'image'`
- An image is a single chunk — no splitting
- Optional user metadata (caption, tags, event context) stored alongside and fed into downstream steps
- Images resized to max 1024px on longest edge, aspect ratio preserved, before any model calls

---

### 2. Classification

A vision-capable model looks at the image and assigns domains from the **shared domain taxonomy** — same taxonomy as text, no separate image taxonomy.

- Same domains: `hobbies/miniature-painting`, `travel`, `business/strategy`, etc.
- Classification prompt adapted: "Look at this image and classify it into domains" vs the text version
- Output: one or more domain tags, same schema as text classification

---

### 3. Entity & Metadata Extraction

This is where images diverge from text. Instead of extracting named entities from prose, a VLLM reads the image and extracts structured visual attributes.

**General image spec (seed):**
```
For each image extract:
- subject: primary subject (person, object, scene, diagram, etc.)
- objects: named or identifiable items visible
- people: anyone identifiable or described
- visible_text: any text in the image (signs, labels, screens)
- setting: indoor/outdoor, location type, context
- style: photograph, screenshot, diagram, illustration, etc.
- shot_type: single, burst, rotation, sequence, or other structural grouping signal
- description: 2-3 sentence description of what the image shows

Output as JSON: { "entities": [...], "description": "...", "tags": [...] }
```

**Domain-specific specs** are simmered once enough images cluster in a domain (threshold: ~20 images). Examples:

- `hobbies/miniature-painting`: model/miniature identity, painting techniques (layering, wet blending, OSL), base style, shoot type, quality signals (sharpness, focus, dramatic angle)
- `travel`: location, landmark, time of day, weather, crowd density, candid vs posed
- `business`: diagram type, whiteboard content, meeting context

The extracted description and entities are the **text representation of the image** — used for text embedding downstream.

---

### 4. Simmering (Image Spec Refinement)

Same simmer-sdk loop as text, adapted for images.

**Phase 1 — Golden Set:** VLLM surveys 10 sample images per domain, builds reference list of what's interesting to extract. Judge verifies against actual images.

**Phase 2 — Spec Refinement:** Iteratively refine the visual extraction spec. Evaluator runs spec against sample images, diffs output against golden set, judge reads raw outputs and gives ASI feedback.

Image specs are a **separate spec lineage** from text specs. Same simmer machinery, different inputs and seeds.

For photography domains, the photo triage spec is simmered here too — shoot type detection, quality ranking criteria, keeper selection rules — all emerge from this phase.

---

### 5. Embedding

Two embeddings per image, stored separately:

| | Model (Cloud) | Model (Local) | Index |
|---|---|---|---|
| **Image pixel embedding** | `multimodalembedding@001` (image path) | SigLIP (image path) | Image index |
| **Image description embedding** | `multimodalembedding@001` (text path) | SigLIP (text path) | Image index |
| **Text doc embedding** | `gemini-embedding-001` | `all-MiniLM-L6-v2` (existing) | Text index |

Both cloud and local use a single specialist model for images — `multimodalembedding@001` and SigLIP respectively — which produce image and text embeddings in the same shared semantic space. A text query embedded through the multimodal model's text path can find images because both modalities live in the same latent space.

The extracted description is embedded through the image model (not the text model), keeping it in the image index's semantic space.

---

### 6. Indexing

**Two specialist indexes:**

**Text index** (existing, unchanged):
- Contains: text chunk embeddings only
- Model: `gemini-embedding-001` (cloud) / sentence-transformers (local)
- Serves: text search across text documents

**Image index** (new):
- Contains: image pixel embeddings + image description embeddings
- Model: `multimodalembedding@001` (cloud) / SigLIP (local)
- Serves: text→image search (text query embedded via multimodal text path), image→image similarity
- Firestore vector field, 1408 dims, well within 2048 limit

**At query time:**
- **Text search**: queries both indexes in parallel. Text index returns text docs, image index returns images (via multimodal text path). Results displayed together as two lists.
- **Image similarity search**: query image index with an image embedding. Returns visually similar images.
- **Cross-modal fusion** (deferred): combining/reranking scores across both indexes into a single ranked list — built later when there's a real use case.

---

### 7. Graph Representation

Image documents appear as nodes in the knowledge graph exactly like text documents. Entities extracted from images create the same co-occurrence edges.

Node additions:
- `content_type: 'image'` flag
- Thumbnail stored for UI display
- `shoot_type` tag for photography content

Edge types added:
- `depicts` — image node → entity it contains
- `same_shoot` — links images from the same session/rotation set (shared parent or manual grouping)

The galaxy viz shows image-sourced entities identically to text-sourced entities. Document nodes get a small visual indicator (icon or thumbnail) showing they're images.

---

## Schema Changes

```sql
-- documents table
ALTER TABLE documents ADD COLUMN content_type TEXT DEFAULT 'text'; -- 'text' or 'image'
ALTER TABLE documents ADD COLUMN image_path TEXT;
ALTER TABLE documents ADD COLUMN thumbnail_path TEXT;


-- chunks table  
ALTER TABLE chunks ADD COLUMN image_embedding VECTOR(1408); -- image specialist embedding
-- existing embedding column becomes text specialist embedding

-- specs table
ALTER TABLE specs ADD COLUMN media_type TEXT DEFAULT 'text'; -- 'text' or 'image'

-- new index: image vector index
-- Firestore: vector field on image_embedding, dimension 1408, flat index
```

---

## What Changes vs What Stays the Same

| File | Current Role | Image Change |
|---|---|---|
| `orchestrator/src/routes/ingest.py` | Accepts text files, chunks, classifies, extracts synchronously | Detect image files, skip chunking (image = 1 chunk), resize to 1024px, pass image to classifier/extractor as base64 |
| `orchestrator/src/pipeline/classifier.py` | Calls `relay.complete_structured()` with text excerpt | For images: pass image as base64 content block instead of text excerpt, image-adapted classification prompt |
| `orchestrator/src/pipeline/extractor.py` | Calls `relay.complete_structured()` with spec + chunk text | For images: pass image as base64 content block alongside the spec |
| `orchestrator/src/pipeline/chunker.py` | Splits text into 2000-char windows | No change — images skip this entirely |
| `orchestrator/src/routes/search.py` | FAISS on text embeddings | Add image description embeddings to text index; add separate image embedding index; type filter on results |
| `worker/src/jobs/simmer_general.py` | Simmers text specs | Separate image spec lineage — branch on `media_type` field on the spec |
| `worker/src/jobs/evaluate_spec.py` | Runs Haiku on text chunks, diffs against golden set | For image specs: pass images to VLLM as base64 instead of text chunks |
| `orchestrator/src/db.py` | Schema | Add `content_type` to documents, `media_type` to specs, `image_path` to chunks, `image_embedding` vector field |
| `frontend/src/components/file-upload.tsx` | Accepts `.txt .md .json .csv` | Add image extensions |
| **Everything else** | — | Unchanged — `normalizer.py`, `cooccurrence.py`, `domain_normalizer.py`, `domain_layout.py`, galaxy viz, MCP server, simmer-sdk all unaffected |

---

## Model Requirements

| Tier | Classification | Extraction | Image Embedding | Text Embedding |
|---|---|---|---|---|
| Cloud | Sonnet 4.6 (vision) | Haiku 4.5 (vision) | `multimodalembedding@001` | `gemini-embedding-001` |
| Local | gemma4:26b (vision) | gemma4:e4b (vision) | SigLIP | sentence-transformers |

---

## Open Questions

1. **Thumbnail generation** — resize on ingest and store, or generate on-the-fly in the UI?
2. **Same-shoot grouping** — how does the system know images are from the same rotation/burst set? Manual folder grouping on upload? Automatic via timestamp + visual similarity?
3. **Cross-modal fusion** — deferred, but what's the trigger to build it? A specific user request? A query pattern we observe?
