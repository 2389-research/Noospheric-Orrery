import uuid
import os
import json
import hashlib
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from anthropic import AsyncAnthropicBedrock

from ..config import get_settings
from ..db import get_connection
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
    conn = get_connection(settings.db_path)
    client = AsyncAnthropicBedrock(
        aws_access_key=settings.aws_access_key,
        aws_secret_key=settings.aws_secret_key,
        aws_region=settings.aws_region,
    )

    try:
        # Dedup: skip if document with same content hash already exists
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        existing = conn.execute(
            "SELECT id, status FROM documents WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing:
            domains = [r[0] for r in conn.execute(
                "SELECT domain_path FROM document_domains WHERE document_id = ?", (existing[0],)
            ).fetchall()]
            conn.close()
            return {
                "document_id": existing[0],
                "title": title,
                "domains": domains,
                "entity_count": 0,
                "jobs_queued": [],
            }

        doc_id = str(uuid.uuid4())

        # 1. Store document
        conn.execute(
            "INSERT INTO documents (id, title, source_path, content, content_hash, status) VALUES (?, ?, ?, ?, ?, 'pending')",
            (doc_id, title, source_path, content, content_hash),
        )

        # 1b. Chunk and store
        chunks = chunk_document(content, chunk_size=settings.chunk_size)
        for chunk in chunks:
            chunk["id"] = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO chunks (id, document_id, chunk_index, offset, length, text) VALUES (?, ?, ?, ?, ?, ?)",
                (chunk["id"], doc_id, chunk["chunk_index"], chunk["offset"], chunk["length"], chunk["text"]),
            )
        conn.commit()

        # 2. Classify
        excerpt = build_classification_excerpt(title, content)
        taxonomy = [row[0] for row in conn.execute("SELECT path FROM domains ORDER BY path").fetchall()]

        classification = await classify_document(
            client=client, title=title, excerpt=excerpt,
            existing_taxonomy=taxonomy, model=settings.classification_model,
        )

        domains = assign_document_domains(conn, doc_id, classification)
        conn.execute("UPDATE documents SET status = 'classified' WHERE id = ?", (doc_id,))
        conn.commit()

        # 3. Extract if general spec exists
        entity_count = 0
        chunk_entities: dict[str, list[str]] = {}
        spec_row = conn.execute(
            "SELECT spec_content, version FROM specs WHERE domain_path IS NULL ORDER BY version DESC LIMIT 1"
        ).fetchone()

        if spec_row:
            spec = spec_row[0]
            spec_version = spec_row[1]
            entities = await extract_document(
                client=client, chunks=chunks, spec=spec, model=settings.extraction_model,
            )
            for entity in entities:
                entity_id = normalize_entity(conn, entity["name"], entity["type"])
                conn.execute(
                    "INSERT INTO entity_sources (entity_id, document_id, chunk_id, extraction_pass, spec_version) VALUES (?, ?, ?, 'general', ?)",
                    (entity_id, doc_id, entity.get("chunk_id"), spec_version),
                )
                chunk_id = entity.get("chunk_id")
                if chunk_id:
                    chunk_entities.setdefault(chunk_id, []).append(entity_id)

            edges = compute_cooccurrence_edges(chunk_entities)
            for edge in edges:
                conn.execute(
                    "INSERT INTO relationships (id, from_entity, to_entity, type, weight, source_chunk) VALUES (?, ?, ?, ?, ?, ?)",
                    (edge["id"], edge["from"], edge["to"], edge["type"], edge["weight"], edge["source_chunk"]),
                )

            entity_count = len(entities)
            conn.execute("UPDATE documents SET status = 'extracted' WHERE id = ?", (doc_id,))
            conn.commit()

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
                domain_spec = conn.execute(
                    "SELECT id, spec_content, version FROM specs WHERE domain_path = ? ORDER BY version DESC LIMIT 1",
                    (ancestor,),
                ).fetchone()

                if domain_spec and domain_spec[0] not in seen_specs:
                    seen_specs.add(domain_spec[0])
                    d_entities = await extract_document(
                        client=client, chunks=chunks,
                        spec=domain_spec[1], model=settings.extraction_model,
                    )
                    for entity in d_entities:
                        entity_id = normalize_entity(conn, entity["name"], entity["type"])
                        conn.execute(
                            "INSERT INTO entity_sources (entity_id, document_id, chunk_id, extraction_pass, spec_version) VALUES (?, ?, ?, 'domain-specific', ?)",
                            (entity_id, doc_id, entity.get("chunk_id"), domain_spec[2]),
                        )
                        chunk_id = entity.get("chunk_id")
                        if chunk_id:
                            chunk_entities.setdefault(chunk_id, []).append(entity_id)
                    domain_entity_count += len(d_entities)

            # Recompute co-occurrence with domain entities included
            if domain_entity_count > 0:
                edges = compute_cooccurrence_edges(chunk_entities)
                for edge in edges:
                    # Upsert — might already have edges from general extraction
                    conn.execute(
                        "INSERT OR REPLACE INTO relationships (id, from_entity, to_entity, type, weight, source_chunk) VALUES (?, ?, ?, ?, ?, ?)",
                        (edge["id"], edge["from"], edge["to"], edge["type"], edge["weight"], edge["source_chunk"]),
                    )

        if domain_entity_count > 0:
            entity_count += domain_entity_count
            conn.execute("UPDATE documents SET status = 'enriched' WHERE id = ?", (doc_id,))
            conn.commit()

        # 5. Check thresholds + queue simmers
        jobs_queued = []

        if not spec_row:
            existing_general_job = conn.execute(
                "SELECT id FROM jobs WHERE type = 'simmer_general' AND status IN ('queued', 'running')"
            ).fetchone()
            if not existing_general_job:
                job_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO jobs (id, type, target, status) VALUES (?, 'simmer_general', 'general', 'queued')",
                    (job_id,),
                )
                jobs_queued.append(job_id)

        for domain_path in domains:
            domain = conn.execute(
                "SELECT document_count, spec_version FROM domains WHERE path = ?", (domain_path,),
            ).fetchone()
            if domain and domain[0] >= settings.domain_spec_threshold and domain[1] is None:
                existing_job = conn.execute(
                    "SELECT id FROM jobs WHERE type = 'simmer_domain' AND target = ? AND status IN ('queued', 'running')",
                    (domain_path,),
                ).fetchone()
                if not existing_job:
                    job_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'simmer_domain', ?, 'queued', ?)",
                        (job_id, domain_path, json.dumps({"domain": domain_path})),
                    )
                    jobs_queued.append(job_id)

        conn.commit()
    finally:
        conn.close()

    # Rebuild search index to include new entities/chunks
    try:
        from ..pipeline.search.retrieval import embed_new_entities, embed_new_chunks
        search_conn = get_connection(settings.db_path)
        embed_new_entities(search_conn)
        embed_new_chunks(search_conn)
        search_conn.close()
    except Exception as e:
        print(f"Search index update after ingest: {e}")

    return {
        "document_id": doc_id,
        "title": title,
        "domains": domains,
        "entity_count": entity_count,
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
