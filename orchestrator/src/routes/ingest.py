# ABOUTME: Ingest route — accepts file uploads (text + images) and directory paths.
# ABOUTME: Handles dedup, chunking, classification, extraction, and job queuing.

import uuid
import os
import json
import hashlib
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Response, status
from orrery_relay import Relay

from ..config import get_settings
from ..dependencies import get_auth_store, AuthStore
from ..models import IngestResult, DirectoryIngestRequest, RepoIngestRequest
from ..pipeline.chunker import chunk_document, chunk_by_sections
from ..pipeline.excerpt import build_classification_excerpt
from ..pipeline.classifier import classify_document
from ..pipeline.domain_normalizer import assign_document_domains
from ..pipeline.extractor import extract_document, extract_document_sectioned
from ..pipeline.normalizer import normalize_entity
from ..pipeline.cooccurrence import compute_cooccurrence_edges
from ..pipeline.image_prep import is_image_file
from ..pipeline.file_extractor import extract_text, NOTEBOOK_EXTENSIONS, PDF_EXTENSIONS, DOCX_EXTENSIONS, ALL_SUPPORTED_EXTENSIONS

router = APIRouter()

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# General specs loaded from orchestrator/specs/*.md — edit those files to update
_SPECS_DIR = Path(__file__).resolve().parent.parent.parent / "specs"


def _load_general_spec(name: str) -> str:
    """Load a general spec from the specs directory."""
    path = _SPECS_DIR / f"{name}.md"
    return path.read_text()


GENERAL_TEXT_SPEC = _load_general_spec("general_text")
GENERAL_IMAGE_SPEC = _load_general_spec("general_image")
GENERAL_CODE_SPEC = _load_general_spec("general_code")

_RESEARCH_PAPER_SPECS_DIR = _SPECS_DIR / "research_paper"


def _load_research_paper_specs() -> dict[str, str]:
    """Compose shared.md + <section>.md for every research_paper section spec,
    plus a "default" key from shared.md + default.md."""
    shared = (_RESEARCH_PAPER_SPECS_DIR / "shared.md").read_text()
    specs = {}
    for path in _RESEARCH_PAPER_SPECS_DIR.glob("*.md"):
        if path.stem == "shared":
            continue
        specs[path.stem] = shared + "\n\n---\n\n" + path.read_text()
    return specs


RESEARCH_PAPER_SPECS = _load_research_paper_specs()

# Domain path that triggers the built-in section-stratified spec directory
# (used when no simmered spec override exists yet for research_paper or its ancestors).
RESEARCH_PAPER_DOMAIN = "research_paper"


def _unique_title(store, title: str) -> str:
    """Keep same-filename uploads distinguishable: if another document already
    has this title, append an incrementing suffix (README.md -> README.md (2)).
    Exact-content duplicates are handled separately by content-hash dedup."""
    if not store.documents.title_exists(title):
        return title
    n = 2
    while store.documents.title_exists(f"{title} ({n})"):
        n += 1
    return f"{title} ({n})"


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
    title = _unique_title(store, title)

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
    domain_entity_count = 0
    seen_specs = set()

    for domain_path in domains:
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
            elif not domain_spec and ancestor == RESEARCH_PAPER_DOMAIN and RESEARCH_PAPER_DOMAIN not in seen_specs:
                seen_specs.add(RESEARCH_PAPER_DOMAIN)
                sectioned_chunks = await chunk_by_sections(
                    relay=relay, text=content, model=settings.extraction_model,
                    chunk_size=settings.chunk_size,
                    overlap=200,  # matches chunk_document's default; update together if that changes
                )
                for c in sectioned_chunks:
                    c["id"] = str(uuid.uuid4())
                # Persist sectioned chunks so relationships.source_chunk and
                # entity_sources.chunk_id reference real rows (not orphaned UUIDs).
                # chunk_index is offset past the general pass's chunks to stay unique
                # per document across both passes.
                sectioned_chunk_objs = [
                    Chunk(
                        id=c["id"],
                        document_id=doc_id,
                        chunk_index=len(chunks) + c["chunk_index"],
                        text=c["text"],
                        offset=c["offset"],
                        length=c["length"],
                        section=c["section"],
                    )
                    for c in sectioned_chunks
                ]
                store.chunks.create_batch(sectioned_chunk_objs)
                d_entities = await extract_document_sectioned(
                    relay=relay, chunks=sectioned_chunks,
                    section_specs=RESEARCH_PAPER_SPECS, model=settings.extraction_model,
                )
                for entity in d_entities:
                    entity_id = normalize_entity(store, entity["name"], entity["type"])
                    store.entity_sources.create(
                        entity_id=entity_id,
                        document_id=doc_id,
                        chunk_id=entity.get("chunk_id"),
                        extraction_pass="domain-specific",
                        # 0 here means "no simmered spec exists yet — built-in
                        # section-stratified spec directory used instead" (distinct
                        # from the general-pass's spec_version=0, which means "no
                        # simmered general spec — built-in GENERAL_TEXT_SPEC used").
                        spec_version=0,
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

    # 5. Queue domain simmers (general spec always available via built-in, no auto-simmer needed)
    jobs_queued = []

    for domain_path in domains:
        domain = store.domains.get(domain_path)
        if domain and domain.document_count >= settings.domain_spec_threshold and domain.spec_version is None:
            existing_job = store.jobs.get_existing("simmer_domain", domain_path, ["queued", "running"])
            if not existing_job:
                job_id = str(uuid.uuid4())
                store.jobs.create(job_id, "simmer_domain", domain_path, {"domain": domain_path})
                jobs_queued.append(job_id)

    # Queue search-index embedding — runs in the worker process, not inline here.
    # Running sentence-transformers/FAISS calls inline raced the orchestrator's own
    # concurrent requests (native SIGBUS crashes); the worker has its own process/
    # address space so it can't collide with them.
    if entity_count > 0:
        existing_job = store.jobs.get_existing("embed_index", "default", ["queued", "running"])
        if not existing_job:
            store.jobs.create(str(uuid.uuid4()), "embed_index", "default")

    return {
        "document_id": doc_id,
        "title": title,
        "domains": domains,
        "entity_count": entity_count,
        "jobs_queued": jobs_queued,
        "content_type": "text",
    }


async def _ingest_image(store, title: str, file_bytes: bytes, image_path: str) -> dict:
    """Ingest an image: describe via vision LLM, classify, extract entities."""
    settings = get_settings()
    relay = Relay.from_settings(settings)

    # Dedup
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    existing = store.documents.get_by_hash(content_hash)
    if existing:
        domains = [d.domain_path for d in store.domains.get_domains_for_document(existing.id)]
        return {
            "document_id": existing.id, "title": title, "domains": domains,
            "entity_count": 0, "jobs_queued": [], "content_type": "image",
        }

    doc_id = str(uuid.uuid4())

    # 1. Describe the image via vision LLM
    from ..pipeline.image_prep import image_to_base64, make_image_content_block
    b64, media_type = image_to_base64(Path(image_path))

    description = ""
    try:
        desc_response = await relay.complete(
            model=settings.classification_model, max_tokens=512,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": "Describe this image in 2-3 sentences. What is it? What details are visible?"},
            ]}],
        )
        description = desc_response.text.strip()
    except Exception as e:
        print(f"Image description failed: {e}", flush=True)
        description = f"Image: {title}"

    # Store document with description as content
    title = _unique_title(store, title)
    store.documents.create(doc_id, title, description, content_hash, image_path, content_type="image")

    # Store a single chunk with the description
    chunk_id = str(uuid.uuid4())
    from ..repositories.interfaces import Chunk
    store.chunks.create_batch([Chunk(
        id=chunk_id, document_id=doc_id, chunk_index=0,
        text=description, offset=0, length=len(description),
    )])

    # 2. Classify using image vision
    from ..pipeline.classifier import classify_image
    taxonomy = store.domains.get_all_paths()

    classification = await classify_image(
        relay=relay, image_base64=b64, media_type=media_type,
        existing_taxonomy=taxonomy, model=settings.classification_model,
    )

    domains = assign_document_domains(store, doc_id, classification)
    store.documents.update_status(doc_id, "classified")

    # 3. Extract entities using general image spec
    entity_count = 0
    chunk_entities: dict[str, list[str]] = {}
    spec = store.specs.get_general()
    spec_content = spec.spec_content if spec else GENERAL_IMAGE_SPEC
    spec_version = spec.version if spec else 0

    # Extract entities from the image description using the spec
    chunks = [{"id": chunk_id, "chunk_index": 0, "text": description, "offset": 0, "length": len(description)}]
    entities = await extract_document(
        relay=relay, chunks=chunks, spec=spec_content, model=settings.extraction_model,
    )
    for entity in entities:
        entity_id = normalize_entity(store, entity["name"], entity["type"])
        store.entity_sources.create(
            entity_id=entity_id, document_id=doc_id,
            chunk_id=chunk_id, extraction_pass="general",
            spec_version=spec_version,
        )
        chunk_entities.setdefault(chunk_id, []).append(entity_id)

    edges = compute_cooccurrence_edges(chunk_entities)
    for edge in edges:
        store.relationships.upsert_cooccurrence(
            edge["id"], edge["from"], edge["to"], edge["weight"], edge["source_chunk"],
        )

    entity_count = len(entities)
    store.documents.update_status(doc_id, "extracted")

    # Queue search-index embedding — see the text-ingest path above for why this
    # runs in the worker process instead of inline (avoids racing the
    # orchestrator's own concurrent requests and the SIGBUS crashes that caused).
    existing_job = store.jobs.get_existing("embed_index", "default", ["queued", "running"])
    if not existing_job:
        store.jobs.create(str(uuid.uuid4()), "embed_index", "default")

    # SigLIP embedding — populates chunks.image_embedding for cross-modal search.
    # Prefers pixel embedding; falls back to description text in the same SigLIP latent space.
    try:
        import numpy as np
        from ..pipeline.image_embedding import embed_image, embed_image_text

        img_emb = embed_image(Path(image_path))
        if img_emb is None and description:
            img_emb = embed_image_text(description)

        if img_emb is not None:
            store.conn.execute(
                "UPDATE chunks SET image_embedding = ? WHERE id = ?",
                (img_emb.astype(np.float32).tobytes(), chunk_id),
            )
            store.conn.commit()
    except Exception as e:
        print(f"SigLIP embedding after image ingest: {e}", flush=True)

    return {
        "document_id": doc_id, "title": title, "domains": domains,
        "entity_count": entity_count, "jobs_queued": [], "content_type": "image",
    }


@router.post("/ingest", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
async def ingest_file(
    response: Response,
    file: UploadFile = File(...),
    auth: AuthStore = Depends(get_auth_store),
):
    file_bytes = await file.read()
    title = file.filename or "untitled"
    settings = get_settings()
    os.makedirs(settings.documents_dir, exist_ok=True)

    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large: max {_MAX_UPLOAD_BYTES // (1024*1024)} MB")

    suffix = Path(title).suffix.lower()
    if suffix not in ALL_SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix or '(no extension)'}")

    store = auth.store
    try:
        if is_image_file(title):
            doc_path = os.path.join(settings.documents_dir, f"{uuid.uuid4()}_{title}")
            with open(doc_path, "wb") as f:
                f.write(file_bytes)
            result = await _ingest_image(store, title, file_bytes, doc_path)
        else:
            try:
                content = extract_text(title, file_bytes)
            except ValueError as e:
                msg = str(e)
                if "magic bytes" in msg:
                    raise HTTPException(status_code=415, detail=msg)
                raise HTTPException(status_code=422, detail=msg)
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Could not extract text from file: {e}")
            doc_path = os.path.join(settings.documents_dir, f"{uuid.uuid4()}_{title}")
            with open(doc_path, "wb") as f:
                f.write(file_bytes)
            result = await _ingest_document(store, title, content, doc_path)
    finally:
        store.close()
    doc_id = result.get("document_id") if isinstance(result, dict) else getattr(result, "document_id", None)
    if doc_id:
        response.headers["Location"] = f"/documents/{doc_id}"
    return result


@router.post("/ingest/directory")
async def ingest_directory(request: DirectoryIngestRequest, auth: AuthStore = Depends(get_auth_store)):
    dir_path = Path(request.path)
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {request.path}")

    store = auth.store
    results = []
    try:
        for file_path in sorted(dir_path.rglob("*")):
            if not file_path.is_file():
                continue
            suffix = file_path.suffix.lower()
            if suffix not in ALL_SUPPORTED_EXTENSIONS:
                continue
            file_bytes = file_path.read_bytes()
            if is_image_file(file_path.name):
                result = await _ingest_image(store, file_path.name, file_bytes, str(file_path))
            else:
                try:
                    content = extract_text(file_path.name, file_bytes)
                except Exception:
                    continue
                result = await _ingest_document(store, file_path.stem, content, str(file_path))
            results.append(result)
    finally:
        store.close()

    return {"documents": results, "total": len(results)}


@router.post("/ingest/repo", status_code=status.HTTP_202_ACCEPTED)
async def ingest_repo(request: RepoIngestRequest, auth: AuthStore = Depends(get_auth_store)):
    dir_path = Path(request.path)
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {request.path}")

    store = auth.store
    try:
        # 1. Seed the general_code spec — reuse the existing general spec row if
        # one exists, otherwise seed it from the built-in general_code.md.
        spec = store.specs.get_general()
        if spec:
            spec_id = spec.id
        else:
            spec_id = str(uuid.uuid4())
            store.specs.create(spec_id, None, 1, GENERAL_CODE_SPEC)

        # 2. Create the repo row directly — there is no RepoRepository abstraction
        # yet, so this uses store.conn (the same raw-SQL escape hatch used
        # elsewhere in this file, e.g. the SigLIP embedding update above).
        repo_id = str(uuid.uuid4())
        store.conn.execute(
            "INSERT INTO repos (id, name, path, root_path) VALUES (?, ?, ?, ?)",
            (repo_id, request.name, request.name, request.path),
        )
        store.conn.commit()

        # 3. Enqueue the Phase-1 (summarize + classify) worker job. Classification
        # is deferred to the worker so it runs on the grounded repo-level summary
        # (read the code, then decide) rather than a README excerpt — see
        # worker/src/jobs/ingest_repo.py.
        job_id = str(uuid.uuid4())
        store.jobs.create(job_id, "ingest_repo", repo_id, {
            "root_path": request.path,
            "repo_id": repo_id,
            "repo_name": request.name,
            "spec_id": spec_id,
        })
    finally:
        store.close()

    return {"job_id": job_id, "repo_id": repo_id}
