import uuid
import os
import json
import hashlib
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from anthropic import AsyncAnthropicBedrock

from ..config import get_settings
from ..repositories.factory import get_store
from ..repositories.interfaces import Chunk
from ..models import IngestResult, DirectoryIngestRequest
from ..pipeline.chunker import chunk_document
from ..pipeline.excerpt import build_classification_excerpt
from ..pipeline.classifier import classify_document
from ..pipeline.domain_normalizer import assign_document_domains
from ..pipeline.extractor import extract_document
from ..pipeline.normalizer import normalize_entity
from ..pipeline.cooccurrence import compute_cooccurrence_edges

router = APIRouter()


async def _ingest_document(title: str, content: str, source_path: str | None) -> dict:
    settings = get_settings()
    store = get_store()
    client = AsyncAnthropicBedrock(
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
    )

    try:
        # Dedup
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        existing = store.documents.get_by_hash(content_hash)
        if existing:
            domains = [d.domain_path for d in store.domains.get_domains_for_document(existing.id)]
            store.close()
            return {
                "document_id": existing.id, "title": title,
                "domains": domains, "entity_count": 0, "jobs_queued": [],
            }

        doc_id = str(uuid.uuid4())

        # 1. Store document
        store.documents.create(doc_id, title, content, content_hash, source_path)

        # 1b. Chunk and store
        raw_chunks = chunk_document(content, chunk_size=settings.chunk_size)
        chunk_objs = []
        for c in raw_chunks:
            c["id"] = str(uuid.uuid4())
            chunk_objs.append(Chunk(
                id=c["id"], document_id=doc_id, chunk_index=c["chunk_index"],
                text=c["text"], offset=c["offset"], length=c["length"],
            ))
        store.chunks.create_batch(chunk_objs)

        # 2. Classify
        excerpt = build_classification_excerpt(title, content)
        taxonomy = store.domains.get_all_paths()

        classification = await classify_document(
            client=client, title=title, excerpt=excerpt,
            existing_taxonomy=taxonomy, model=settings.classification_model,
        )

        domains = assign_document_domains(store, doc_id, classification)
        store.documents.update_status(doc_id, "classified")

        # 3. Extract if general spec exists
        entity_count = 0
        chunk_entities: dict[str, list[str]] = {}
        general_spec = store.specs.get_general()

        if general_spec:
            entities = await extract_document(
                client=client, chunks=raw_chunks,
                spec=general_spec.spec_content, model=settings.extraction_model,
            )
            for entity in entities:
                entity_id = normalize_entity(store, entity["name"], entity["type"])
                store.entity_sources.create(
                    entity_id, doc_id, entity.get("chunk_id"),
                    "general", general_spec.version,
                )
                chunk_id = entity.get("chunk_id")
                if chunk_id:
                    chunk_entities.setdefault(chunk_id, []).append(entity_id)

            edges = compute_cooccurrence_edges(chunk_entities)
            for edge in edges:
                store.relationships.upsert_cooccurrence(
                    edge["id"], edge["from"], edge["to"],
                    edge["weight"], edge["source_chunk"],
                )

            entity_count = len(entities)
            store.documents.update_status(doc_id, "extracted")

        # 4. Cascade through domain specs
        domain_entity_count = 0
        seen_specs = set()

        for domain_path in domains:
            parts = domain_path.split("/")
            ancestor_paths = ["/".join(parts[:i+1]) for i in range(len(parts))]

            for ancestor in reversed(ancestor_paths):
                domain_spec = store.specs.get_for_domain(ancestor)
                if domain_spec and domain_spec.id not in seen_specs:
                    seen_specs.add(domain_spec.id)
                    d_entities = await extract_document(
                        client=client, chunks=raw_chunks,
                        spec=domain_spec.spec_content, model=settings.extraction_model,
                    )
                    for entity in d_entities:
                        entity_id = normalize_entity(store, entity["name"], entity["type"])
                        store.entity_sources.create(
                            entity_id, doc_id, entity.get("chunk_id"),
                            "domain-specific", domain_spec.version,
                        )
                        chunk_id = entity.get("chunk_id")
                        if chunk_id:
                            chunk_entities.setdefault(chunk_id, []).append(entity_id)
                    domain_entity_count += len(d_entities)

            if domain_entity_count > 0:
                edges = compute_cooccurrence_edges(chunk_entities)
                for edge in edges:
                    store.relationships.upsert_cooccurrence(
                        edge["id"], edge["from"], edge["to"],
                        edge["weight"], edge["source_chunk"],
                    )

        if domain_entity_count > 0:
            entity_count += domain_entity_count
            store.documents.update_status(doc_id, "enriched")

        # 5. Check thresholds + queue simmers
        jobs_queued = []

        if not general_spec:
            existing_job = store.jobs.get_existing("simmer_general", "general", ["queued", "running"])
            if not existing_job:
                job_id = str(uuid.uuid4())
                store.jobs.create(job_id, "simmer_general", "general")
                jobs_queued.append(job_id)

        for domain_path in domains:
            domain = store.domains.get(domain_path)
            if domain and domain.document_count >= settings.domain_spec_threshold and domain.spec_version is None:
                existing_job = store.jobs.get_existing("simmer_domain", domain_path, ["queued", "running"])
                if not existing_job:
                    job_id = str(uuid.uuid4())
                    store.jobs.create(job_id, "simmer_domain", domain_path, config={"domain": domain_path})
                    jobs_queued.append(job_id)

    finally:
        store.close()

    # Rebuild search index
    try:
        from ..pipeline.search.retrieval import embed_new_entities, embed_new_chunks
        search_store = get_store()
        # Search still needs raw conn for FAISS operations
        if search_store.conn is not None:
            embed_new_entities(search_store.conn)
            embed_new_chunks(search_store.conn)
        search_store.close()
    except Exception as e:
        print(f"Search index update after ingest: {e}")

    return {
        "document_id": doc_id, "title": title,
        "domains": domains, "entity_count": entity_count,
        "jobs_queued": jobs_queued,
    }


@router.post("/ingest", response_model=IngestResult)
async def ingest_file(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8")
    title = file.filename or "untitled"

    settings = get_settings()
    os.makedirs(settings.documents_dir, exist_ok=True)
    doc_path = os.path.join(settings.documents_dir, f"{uuid.uuid4()}_{title}")
    with open(doc_path, "w") as f:
        f.write(content)

    return await _ingest_document(title, content, doc_path)


@router.post("/ingest/directory")
async def ingest_directory(request: DirectoryIngestRequest):
    dir_path = Path(request.path)
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {request.path}")

    results = []
    for file_path in sorted(dir_path.rglob("*")):
        if file_path.is_file() and file_path.suffix in (".txt", ".md", ".json", ".csv"):
            content = file_path.read_text(errors="replace")
            result = await _ingest_document(file_path.stem, content, str(file_path))
            results.append(result)

    return {"documents": results, "total": len(results)}
