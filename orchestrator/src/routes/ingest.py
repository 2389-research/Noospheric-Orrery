import uuid
import os
import json
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from anthropic import AsyncAnthropic

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
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        doc_id = str(uuid.uuid4())

        # 1. Store document
        conn.execute(
            "INSERT INTO documents (id, title, source_path, content, status) VALUES (?, ?, ?, ?, 'pending')",
            (doc_id, title, source_path, content),
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
        spec_row = conn.execute(
            "SELECT spec_content, version FROM specs WHERE domain_path IS NULL ORDER BY version DESC LIMIT 1"
        ).fetchone()

        if spec_row:
            spec = spec_row[0]
            spec_version = spec_row[1]
            entities = await extract_document(
                client=client, chunks=chunks, spec=spec, model=settings.extraction_model,
            )

            chunk_entities: dict[str, list[str]] = {}
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

        # 4. Check thresholds
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
