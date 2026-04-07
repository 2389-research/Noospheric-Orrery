# Image Pipeline — Current Status

**Date:** 2026-04-07
**Branch:** `feat/image-pipeline`

## What's Working

- Upload images via POST /ingest — auto-detects, classifies, extracts entities/description
- Text search finds images via embedded descriptions
- Parallel search with `include_images=true`
- Image serving endpoint: GET /images/{document_id}
- Orrery viz: star view shows image docs, clicking opens ImagePane with actual photo
- ImagePane: shows image + grouped entities (clickable navigation) + domains + description
- Co-occurrence edges computed for image entities
- Star view passes content_type for correct panel routing
- Image simmering job type wired into worker
- Simmered seed spec (9.0/10) with representation layer, color entities, medium/shot_type fields
- CPU-only torch via pyproject.toml index config (200MB vs 5GB)
- Sonnet as clerk model for reliable score parsing

## Currently Running

Image simmer job — Phase 1 golden set in progress. Previous run completed Phase 1 (7.7 best) but Phase 2 failed due to missing --media-type argument in evaluator. That's now fixed.

## Remaining

- Verify Phase 2 completes with the evaluator fix
- SigLIP native image embeddings (module written, not tested in Docker)
- Domain-specific image simmering (not built yet — same pattern as text)
- Thumbnail generation on ingest (code exists but not integrated into Docker Pillow)
- Test with diverse image types (portfolio photos via the UI)
