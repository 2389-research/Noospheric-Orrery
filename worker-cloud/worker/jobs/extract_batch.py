"""Batch entity extraction from documents using a simmered spec.

Extracts entities, then delegates to post_process for:
embed → cooccurrences → UMAP layout → graph cache.
"""
import os
import uuid
import json
from datetime import datetime, timezone
from google.cloud import firestore


async def run_extract_batch(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    """Run batch extraction then post-processing pipeline."""
    from anthropic import AsyncAnthropicBedrock

    # Load spec
    spec_config = job.get("config", {})
    spec_id = spec_config.get("spec_id")
    spec_col = db.collection(f"workspaces/{workspace_id}/specs")

    if spec_id:
        spec_doc = spec_col.document(spec_id).get()
        spec_content = spec_doc.to_dict().get("specContent", "")
        spec_version = spec_doc.to_dict().get("version", 1)
    else:
        specs = list(spec_col.where("domainPath", "==", None).stream())
        if not specs:
            raise ValueError("No spec found for extraction")
        spec = max(specs, key=lambda s: s.to_dict().get("version", 0))
        spec_content = spec.to_dict().get("specContent", "")
        spec_version = spec.to_dict().get("version", 1)
        spec_id = spec.id

    if not spec_content:
        raise ValueError(f"Spec {spec_id} has no content")

    print(f"Running batch extraction with spec {spec_id} (v{spec_version})", flush=True)

    # Get documents
    doc_col = db.collection(f"workspaces/{workspace_id}/documents")
    docs = list(doc_col.where("status", "in", ["classified", "extracted", "enriched"]).stream())

    client = AsyncAnthropicBedrock(
        aws_access_key=os.environ.get("AWS_ACCESS_KEY", ""),
        aws_secret_key=os.environ.get("AWS_SECRET_KEY", ""),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
    )
    extraction_model = os.environ.get("EXTRACTION_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

    total_entities = 0
    entity_col = db.collection(f"workspaces/{workspace_id}/entities")
    source_col = db.collection(f"workspaces/{workspace_id}/entitySources")
    chunk_col = db.collection(f"workspaces/{workspace_id}/chunks")

    print(f"Processing {len(docs)} documents", flush=True)

    for doc_snap in docs:
        doc = doc_snap.to_dict()
        doc_id = doc_snap.id
        if not doc.get("content"):
            continue

        chunks = list(chunk_col.where("documentId", "==", doc_id).stream())
        chunks.sort(key=lambda c: c.to_dict().get("chunkIndex", 0))

        for chunk_snap in chunks:
            chunk_text = chunk_snap.to_dict().get("text", "")
            if not chunk_text:
                continue

            try:
                response = await client.messages.create(
                    model=extraction_model, max_tokens=4096,
                    messages=[{"role": "user", "content": f"{spec_content}\n\nDocument text:\n{chunk_text}"}],
                )
                text = response.content[0].text
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]

                text = text.strip()
                if text.startswith("["):
                    entities = json.loads(text)
                elif text.startswith("{"):
                    entities = [json.loads(line) for line in text.splitlines() if line.strip().startswith("{")]
                else:
                    entities = []
            except Exception as e:
                print(f"  Extraction failed for chunk {chunk_snap.id}: {e}", flush=True)
                entities = []

            for ent in entities:
                name = ent.get("name", "").lower().strip()
                etype = ent.get("type", "Thing")
                if not name or len(name) < 2:
                    continue

                existing = list(entity_col.where("canonicalName", "==", name).where("type", "==", etype).limit(1).stream())
                if existing:
                    entity_id = existing[0].id
                    entity_col.document(entity_id).update({"sourceCount": firestore.Increment(1)})
                else:
                    entity_id = str(uuid.uuid4())
                    entity_col.document(entity_id).set({
                        "canonicalName": name, "type": etype, "sourceCount": 1,
                        "createdAt": datetime.now(timezone.utc),
                    })

                source_col.add({
                    "entityId": entity_id, "documentId": doc_id,
                    "chunkId": chunk_snap.id, "extractionPass": "batch",
                    "specVersion": spec_version, "jobId": job_id,
                })
                total_entities += 1

        doc_col.document(doc_id).update({"status": "extracted"})
        print(f"  Processed {doc.get('title', doc_id)}", flush=True)

    print(f"Extraction done: {total_entities} entities from {len(docs)} docs", flush=True)

    # Run shared post-processing pipeline
    from worker.jobs.post_process import run_post_processing
    run_post_processing(db, workspace_id)

    # Update job result
    db.collection(f"workspaces/{workspace_id}/jobs").document(job_id).update({
        "result": {"total_entities": total_entities, "documents_processed": len(docs)},
    })

    print(f"Batch extraction complete!", flush=True)
