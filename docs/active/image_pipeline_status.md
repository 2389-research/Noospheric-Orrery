# Image Pipeline — Status

**Date:** 2026-04-08
**Branch:** `feat/image-pipeline` — ready for PR

## Working End-to-End

- Upload images via UI → classify into domains (no extraction until spec exists)
- Simmer triggers after batch upload completes (frontend calls POST /simmer/general/image)
- Single-stage domain simmer: general spec seed → add domain context → evaluate with Haiku → 2.7→7.3
- Batch extraction with simmered spec: 87 entities across 5 images
- Text + image search with toggle (📷 on/off)
- Image results show thumbnails at top of search results
- Clicking image opens ImagePane with photo + entities + description
- Star view shows image docs with co-occurrence entities
- Image serving endpoint: GET /images/{document_id}

## Architecture

- **Text pipeline**: 2-stage simmer (golden set → extraction spec) — entity types vary by domain
- **Image pipeline**: 1-stage simmer (general spec + domain context) — entity types are stable, domain context adds recognition
- **Search**: Two specialist indexes (sentence-transformers for text, SigLIP for images)
- **Judges**: Sonnet reasons, Haiku does vision (query_image tool + pre-scans + evaluator)

## Remaining Polish

- Frontend rebuild needed for latest search UI fixes
- SigLIP embeddings not computed during batch extraction (falls back to sentence-transformers)
- Domain-specific image simmering not wired into worker dispatch (POC tested)
- Default iteration count should be 3 (seed + 3)
