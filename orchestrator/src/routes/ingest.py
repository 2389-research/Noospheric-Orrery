# ABOUTME: Ingest route — accepts file uploads and directory paths, runs the full pipeline.
# ABOUTME: Handles dedup, chunking, classification, extraction, and job queuing.

import uuid
import os
import json
import hashlib
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from orrery_relay import Relay

from ..config import get_settings
from ..dependencies import get_auth_store, AuthStore
from ..models import IngestResult, DirectoryIngestRequest
from ..pipeline.chunker import chunk_document
from ..pipeline.excerpt import build_classification_excerpt
from ..pipeline.classifier import classify_document
from ..pipeline.domain_normalizer import assign_document_domains
from ..pipeline.extractor import extract_document
from ..pipeline.normalizer import normalize_entity
from ..pipeline.cooccurrence import compute_cooccurrence_edges
from ..pipeline.image_prep import is_image_file

router = APIRouter()

# General specs loaded from orchestrator/specs/*.md — edit those files to update
_SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"


def _load_general_spec(name: str) -> str:
    """Load a general spec from the specs directory."""
    path = _SPECS_DIR / f"{name}.md"
    return path.read_text()


GENERAL_TEXT_SPEC = _load_general_spec("general_text")
GENERAL_IMAGE_SPEC = _load_general_spec("general_image")


async def _ingest_document(store, title: str, content: str, source_path: str | None) -> dict:
    settings = get_settings()
    relay = Relay.from_settings(settings)

    # Dedup: skip if document with same content hash already exists
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    existing = store.documents.get_by_hash(content_hash)
    if existing:
        domains = [d.domain_path for d in store.domains.get_domains_for_document(existing.id)]
        return {
            "document_id": existing.id,
            "title": title,
            "domains": domains,
            "entity_count": 0,
            "jobs_queued": [],
            "content_type": "text",
        }

    doc_id = str(uuid.uuid4())

    # 1. Store document
    store.documents.create(doc_id, title, content, content_hash, source_path)

    # 1b. Chunk and store
    chunks = chunk_document(content, chunk_size=settings.chunk_size)
    from ..repositories.interfaces import Chunk
    chunk_objs = []
    for chunk in chunks:
        chunk["id"] = str(uuid.uuid4())
        chunk_objs.append(Chunk(
            id=chunk["id"],
            document_id=doc_id,
            chunk_index=chunk["chunk_index"],
            text=chunk["text"],
            offset=chunk["offset"],
            length=chunk["length"],
        ))
    store.chunks.create_batch(chunk_objs)

    # 2. Classify
    excerpt = build_classification_excerpt(title, content)
    taxonomy = store.domains.get_all_paths()

    classification = await classify_document(
        relay=relay, title=title, excerpt=excerpt,
        existing_taxonomy=taxonomy, model=settings.classification_model,
    )

    domains = assign_document_domains(store, doc_id, classification)
    store.documents.update_status(doc_id, "classified")

    # 3. Extract — use simmered general spec if available, otherwise built-in general spec
    entity_count = 0
    chunk_entities: dict[str, list[str]] = {}
    spec = store.specs.get_general()
    spec_content = spec.spec_content if spec else GENERAL_TEXT_SPEC
    spec_version = spec.version if spec else 0
    extraction_pass = "general_simmered" if spec else "general"

    entities = await extract_document(
        relay=relay, chunks=chunks, spec=spec_content, model=settings.extraction_model,
    )
    for entity in entities:
        entity_id = normalize_entity(store, entity["name"], entity["type"])
        store.entity_sources.create(
            entity_id=entity_id,
            document_id=doc_id,
            chunk_id=entity.get("chunk_id"),
            extraction_pass=extraction_pass,
            spec_version=spec_version,
        )
        chunk_id = entity.get("chunk_id")
        if chunk_id:
            chunk_entities.setdefault(chunk_id, []).append(entity_id)

    edges = compute_cooccurrence_edges(chunk_entities)
    for edge in edges:
        store.relationships.upsert_cooccurrence(
            edge["id"], edge["from"], edge["to"], edge["weight"], edge["source_chunk"],
        )

    entity_count = len(entities)
    store.documents.update_status(doc_id, "extracted")

    # 4. Cascade through domain specs
    #    For each domain this doc belongs to, walk up the tree and
    #    run any domain-specific specs that exist.
    #    e.g., doc in business/product_development/strategy/ecommerce
    #    checks: ecommerce spec, strategy spec, product_development spec
    domain_entity_count = 0
    seen_specs = set()

    for domain_path in domains:
        # Walk up the domain tree: a/b/c → [a/b/c, a/b, a]
        parts = domain_path.split("/")
        ancestor_paths = ["/".join(parts[:i+1]) for i in range(len(parts))]

        for ancestor in reversed(ancestor_paths):  # deepest first
            domain_spec = store.specs.get_for_domain(ancestor)

            if domain_spec and domain_spec.id not in seen_specs:
                seen_specs.add(domain_spec.id)
                d_entities = await extract_document(
                    relay=relay, chunks=chunks,
                    spec=domain_spec.spec_content, model=settings.extraction_model,
                )
                for entity in d_entities:
                    entity_id = normalize_entity(store, entity["name"], entity["type"])
                    store.entity_sources.create(
                        entity_id=entity_id,
                        document_id=doc_id,
                        chunk_id=entity.get("chunk_id"),
                        extraction_pass="domain-specific",
                        spec_version=domain_spec.version,
                    )
                    chunk_id = entity.get("chunk_id")
                    if chunk_id:
                        chunk_entities.setdefault(chunk_id, []).append(entity_id)
                domain_entity_count += len(d_entities)

        # Recompute co-occurrence with domain entities included
        if domain_entity_count > 0:
            edges = compute_cooccurrence_edges(chunk_entities)
            for edge in edges:
                store.relationships.upsert_cooccurrence(
                    edge["id"], edge["from"], edge["to"], edge["weight"], edge["source_chunk"],
                )

    if domain_entity_count > 0:
        entity_count += domain_entity_count
        store.documents.update_status(doc_id, "enriched")

    # 5. Check thresholds + queue domain simmers (general spec always available, no auto-simmer needed)
    jobs_queued = []

    for domain_path in domains:
        domain = store.domains.get(domain_path)
        if domain and domain.document_count >= settings.domain_spec_threshold and domain.spec_version is None:
            existing_job = store.jobs.get_existing("simmer_domain", domain_path, ["queued", "running"])
            if not existing_job:
                job_id = str(uuid.uuid4())
                store.jobs.create(job_id, "simmer_domain", domain_path, {"domain": domain_path})
                jobs_queued.append(job_id)

    # Queue post-processing if entities were extracted
    # Handles: embedding, cooccurrences, UMAP layout, graph cache rebuild
    if entity_count > 0:
        import os as _os
        if _os.environ.get("DB_BACKEND", "sqlite").lower() == "firestore":
            existing_pp = store.jobs.get_existing("post_process", "general", ["queued", "running"])
            if not existing_pp:
                pp_id = str(uuid.uuid4())
                store.jobs.create(pp_id, "post_process", "general")
                jobs_queued.append(pp_id)
        else:
            # SQLite: rebuild search index inline
            try:
                from ..pipeline.search.retrieval import embed_new_entities, embed_new_chunks
                embed_new_entities(store.conn)
                embed_new_chunks(store.conn)
            except Exception as e:
                print(f"Search index update after ingest: {e}")

    return {
        "document_id": doc_id,
        "title": title,
        "domains": domains,
        "entity_count": entity_count,
        "jobs_queued": jobs_queued,
        "content_type": "text",
    }


async def _ingest_image(store, title: str, file_bytes: bytes, image_path: str) -> dict:
    """Ingest an image: classify via VLLM, extract entities/description, store."""
    from ..pipeline.image_prep import image_to_base64, make_thumbnail
    from ..pipeline.classifier import classify_image
    from ..pipeline.extractor import extract_entities_from_image

    settings = get_settings()
    relay = Relay.from_settings(settings)

    # Dedup by content hash
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    existing = store.documents.get_by_hash(content_hash)
    if existing:
        domains = [d.domain_path for d in store.domains.get_domains_for_document(existing.id)]
        return {
            "document_id": existing.id, "title": title, "domains": domains,
            "entity_count": 0, "jobs_queued": [], "content_type": "image",
        }

    # Encode for VLLM
    b64, media_type = image_to_base64(Path(image_path))

    # Generate thumbnail
    thumb_dir = Path(settings.documents_dir) / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = str(make_thumbnail(Path(image_path), thumb_dir / f"{Path(image_path).stem}_thumb.jpg"))

    doc_id = str(uuid.uuid4())

    # Cloud mode: upload images to Firebase Storage
    stored_image_path = image_path
    stored_thumb_path = thumb_path
    if os.environ.get("DB_BACKEND", "sqlite").lower() == "firestore":
        try:
            from ..services.image_storage import upload_image
            storage_img = f"images/{doc_id}/{Path(image_path).name}"
            upload_image(image_path, storage_img)
            stored_image_path = storage_img

            storage_thumb = f"images/{doc_id}/thumbnail.jpg"
            upload_image(thumb_path, storage_thumb)
            stored_thumb_path = storage_thumb
        except Exception as e:
            print(f"Firebase Storage upload failed, using local path: {e}", flush=True)

    # Classify
    taxonomy = store.domains.get_all_paths()
    classification = await classify_image(
        relay=relay, image_base64=b64, media_type=media_type,
        existing_taxonomy=taxonomy, model=settings.classification_model,
    )
    domains = assign_document_domains(store, doc_id, classification)

    # Store document
    store.documents.create(
        doc_id, title, "", content_hash, stored_image_path,
        content_type="image", image_path=stored_image_path, thumbnail_path=stored_thumb_path,
    )
    store.documents.update_status(doc_id, "classified")

    # Store single chunk (empty for now — batch extraction fills in description + entities)
    from ..repositories.interfaces import Chunk
    chunk_id = str(uuid.uuid4())
    store.chunks.create_batch([Chunk(
        id=chunk_id, document_id=doc_id, chunk_index=0,
        text="", offset=0, length=0,
    )])

    # Extract with simmered spec if available, otherwise use general spec
    entity_count = 0
    image_spec = store.specs.get_general(media_type="image")
    spec_content = image_spec.spec_content if image_spec else GENERAL_IMAGE_SPEC
    spec_version = image_spec.version if image_spec else 0
    extraction_pass = "image_simmered" if image_spec else "image_general"

    extraction = await extract_entities_from_image(
        relay=relay, image_base64=b64, media_type=media_type,
        spec=spec_content, model=settings.extraction_model,
    )

    description = extraction.get("description", "")

    # Update document content with description
    store.documents.update_content(doc_id, description)
    store.chunks.update_text(chunk_id, description)

    chunk_entities: dict[str, list[str]] = {}
    for entity in extraction.get("entities", []):
        name = entity.get("name", "").lower().strip()
        etype = entity.get("type", "Object")
        if not name:
            continue
        entity_id = normalize_entity(store, name, etype)
        store.entity_sources.create(
            entity_id=entity_id, document_id=doc_id, chunk_id=chunk_id,
            extraction_pass=extraction_pass,
            spec_version=spec_version,
        )
        chunk_entities.setdefault(chunk_id, []).append(entity_id)
        entity_count += 1

    if chunk_entities:
        edges = compute_cooccurrence_edges(chunk_entities)
        for edge in edges:
            store.relationships.upsert_cooccurrence(
                edge["id"], edge["from"], edge["to"], edge["weight"], edge["source_chunk"],
            )
    store.documents.update_status(doc_id, "extracted")

    # Embed for search
    import os as _os
    if _os.environ.get("DB_BACKEND", "sqlite").lower() == "firestore":
        # Cloud: embed description with Vertex AI for vector search
        if description:
            try:
                from ..services.embedding import embed_text
                from google.cloud.firestore_v1.vector import Vector
                desc_embedding = embed_text(description)
                store.chunks.update_embedding(chunk_id, Vector(desc_embedding))
            except Exception as e:
                print(f"Vertex AI embedding after image ingest: {e}", flush=True)
    else:
        # Text embeddings (sentence-transformers) for text search compatibility
        try:
            from ..pipeline.search.retrieval import embed_new_entities, embed_new_chunks
            embed_new_entities(store.conn)
            embed_new_chunks(store.conn)
        except Exception as e:
            print(f"Text embedding after image ingest: {e}")

        # SigLIP embeddings (image + description) for native image search
        try:
            from ..pipeline.image_embedding import embed_image, embed_image_text
            import numpy as np

            # Embed the image pixels
            img_emb = embed_image(Path(image_path))
            if img_emb is not None:
                store.conn.execute(
                    "UPDATE chunks SET image_embedding = ? WHERE id = ?",
                    (img_emb.astype(np.float32).tobytes(), chunk_id),
                )

            # Embed the description via SigLIP text path (same latent space as image)
            if description:
                desc_emb = embed_image_text(description)
                if desc_emb is not None:
                    # Store as a second embedding — could use a separate column or append
                    # For now, if image_embedding is empty, store the description embedding there
                    if img_emb is None:
                        store.conn.execute(
                            "UPDATE chunks SET image_embedding = ? WHERE id = ?",
                            (desc_emb.astype(np.float32).tobytes(), chunk_id),
                        )

            store.conn.commit()
        except Exception as e:
            print(f"SigLIP embedding after image ingest: {e}")

    # Image simmer is user-triggered via POST /simmer/general/image
    # (no auto-trigger — user uploads batch first, then decides to simmer)
    jobs_queued = []

    return {
        "document_id": doc_id, "title": title, "domains": domains,
        "entity_count": entity_count, "jobs_queued": jobs_queued, "content_type": "image",
    }


@router.post("/ingest", response_model=IngestResult)
async def ingest_file(file: UploadFile = File(...), auth: AuthStore = Depends(get_auth_store)):
    file_bytes = await file.read()
    title = file.filename or "untitled"
    settings = get_settings()
    os.makedirs(settings.documents_dir, exist_ok=True)

    store = auth.store
    try:
        if is_image_file(title):
            # Save image as binary
            doc_path = os.path.join(settings.documents_dir, f"{uuid.uuid4()}_{title}")
            with open(doc_path, "wb") as f:
                f.write(file_bytes)
            result = await _ingest_image(store, title, file_bytes, doc_path)
        else:
            # Text file — existing path
            content = file_bytes.decode("utf-8")
            doc_path = os.path.join(settings.documents_dir, f"{uuid.uuid4()}_{title}")
            with open(doc_path, "w") as f:
                f.write(content)
            result = await _ingest_document(store, title, content, doc_path)
    finally:
        store.close()
    return result


@router.post("/ingest/directory")
async def ingest_directory(request: DirectoryIngestRequest, auth: AuthStore = Depends(get_auth_store)):
    dir_path = Path(request.path)
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {request.path}")

    store = auth.store
    results = []
    try:
        text_exts = {".txt", ".md", ".json", ".csv"}
        image_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        for file_path in sorted(dir_path.rglob("*")):
            if not file_path.is_file():
                continue
            suffix = file_path.suffix.lower()
            if suffix in text_exts:
                content = file_path.read_text(errors="replace")
                result = await _ingest_document(store, file_path.stem, content, str(file_path))
                results.append(result)
            elif suffix in image_exts:
                file_bytes = file_path.read_bytes()
                result = await _ingest_image(store, file_path.name, file_bytes, str(file_path))
                results.append(result)
    finally:
        store.close()

    return {"documents": results, "total": len(results)}
