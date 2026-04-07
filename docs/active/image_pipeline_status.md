# Image Pipeline — Current Status & Next Steps

**Date:** 2026-04-07
**Branch:** `feat/image-pipeline`

---

## What's Built and Tested

### Pipeline Core (all working end-to-end)

| Component | Status | Verified |
|-----------|--------|----------|
| Schema (content_type, image_path, thumbnail_path, image_embedding, media_type) | Done | Tests pass |
| Image preprocessing (resize, thumbnail, base64, lazy PIL) | Done | Tested locally |
| classify_image() — VLLM classifies images into shared domain taxonomy | Done | Tested via Bedrock Sonnet against Warhammer + portfolio images |
| extract_entities_from_image() — VLLM extracts entities/desc/tags/medium/shot_type/representation | Done | Tested via Bedrock Haiku, produces rich searchable output |
| POST /ingest — auto-detects images, routes to _ingest_image() | Done | Tested via curl, 200 OK, domains assigned, entities stored |
| POST /ingest/directory — handles mixed text + image folders | Done | Code complete |
| GET /search?include_images=true — parallel image results | Done | Tested, returns scored image results with descriptions |
| Image simmering (run_simmer_general_image) | Done | Code + worker dispatch wired, not yet run |
| Evaluator --media-type image | Done | Code complete, not yet run in a simmer loop |
| SigLIP embedding module (image_embedding.py) | Done | Code complete, lazy-loaded, batch support |
| Frontend accepts image uploads (.jpg .png .webp .gif) | Done | file-upload.tsx updated |
| Simmered image seed spec | Done | 9.0/10, validated against Haiku with diverse images |

### What Was Validated End-to-End

1. **Upload 17 Warhammer miniature photos** → classified as miniature-painting/wargaming/tabletop-gaming
2. **132 entities extracted** across all images (subjects, objects, materials, colors, settings)
3. **Text search finds images** — "painted warrior miniature with metallic armor" returns DSCF3680.jpg at 0.68 similarity
4. **Parallel search works** — text and image results returned separately, scored independently
5. **Simmered spec produces excellent output** — "representation layer" distinguishes miniatures from real objects, descriptions lead with medium + subject, tags add search surface

---

## What Needs Testing Next

### 1. Rebuild Docker and test full UI flow

The orchestrator container needs rebuilding with the latest code. Then:

```bash
git checkout feat/image-pipeline
docker-compose build orchestrator frontend
docker-compose up -d
```

Test:
- Open http://localhost:3100, upload an image via the UI
- Check it appears in the pipeline page with content_type='image'
- Check entities page shows image-sourced entities
- Search with `include_images=true` param

### 2. Run image simmering via the worker

There's a queued `simmer_general_image` job from the cherry blossom upload. Rebuild the worker and let it run:

```bash
docker-compose build worker
docker-compose up -d worker
docker logs -f noospheric-orrery-worker-1
```

Watch for Phase 1 (golden set from sample images) and Phase 2 (extraction spec with evaluator). The simmered seed spec should produce good starting scores.

### 3. Test SigLIP embeddings

The `image_embedding.py` module is written but not tested in Docker. Needs `transformers` and `torch` in the orchestrator container (same as sentence-transformers). Test:

```python
from src.pipeline.image_embedding import embed_image, embed_image_text
emb = embed_image(Path("/data/test_images/DSCF3676.jpg"))
print(emb.shape)  # Should be (768,) or similar
```

### 4. Test with the portfolio photos

Upload the 4 portfolio photos (Great Wall, kanji, banksia, tropical plant) through the UI. Verify:
- Classification creates new domains (art, travel, nature) separate from miniature-painting
- Entities are general, not Warhammer-biased
- Descriptions are accurate and searchable

---

## What Remains to Build

### Task 9: Orrery Viz Integration

Image documents need to appear in the galaxy map:
- **Graph API** (`graph.py`): include content_type and thumbnail_path on document nodes
- **cosmic-viz.html**: check content_type, render image docs with camera icon or thumbnail
- **Entity detail panel**: clicking an entity shows both text docs AND images
- **Star/solar system view**: image documents orbit entity stars with thumbnails
- **Image viewer**: clicking an image doc opens full image + description + entities

This is frontend work. The data is already in the graph — images produce the same entities and co-occurrence edges as text. The viz just needs to render image document nodes differently.

### Domain-Specific Image Simmering

Not yet built. Same pattern as text domain simmering:
- When 20+ images cluster in a domain (e.g., `hobbies/miniature-painting`)
- Simmer a domain visual spec that extracts domain-specific entities
- For miniatures: painting techniques, model identity, army faction, base style
- For travel: landmarks, time of day, weather, local signage
- Builds on the general spec (doesn't replace it)

### Pillow in Docker

Pillow is in pyproject.toml but the orchestrator Dockerfile.local uses `uv sync --frozen` which may not pick it up without a lockfile update. Need to verify:

```bash
docker exec noospheric-orrery-orchestrator-1 uv run python -c "from PIL import Image; print('OK')"
```

If it fails, update the lockfile: `cd orchestrator && uv lock` and rebuild.

---

## PRs (all merged)

- **PR #13**: Judgment parser fixes — merged
- **PR #14**: Ollama backend — merged

Next: rebase `feat/image-pipeline` onto main, create PR.

---

## Architecture Summary

```
Image Upload → save binary → resize/thumbnail → classify_image (Sonnet)
                                                      ↓
                                              assign domains
                                                      ↓
                                          extract_entities_from_image (Haiku)
                                                      ↓
                                    entities + description + tags + medium + shot_type + representation
                                                      ↓
                              normalize entities → store → cooccurrence edges → embed
                                                      ↓
                                          searchable via GET /search?include_images=true

Simmering: same two-phase pattern as text
  Phase 1: VLLM surveys sample images → reference entity/description list
  Phase 2: Iteratively refine visual extraction spec → evaluator runs VLLM on images

Three embedding paths per image (future):
  1. Image pixels → SigLIP image path → image index
  2. Description text → SigLIP text path → image index  
  3. Entity names → SigLIP text path → image index

Text documents stay in their own index (sentence-transformers). No cross-pollination.
Default search: text only. Image search: opt-in via include_images=true.
```
