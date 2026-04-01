"""Batch extraction — runs a spec against all docs in scope.

Reads spec from Firestore, extracts entities from each doc's chunks,
normalizes and stores back to Firestore.
"""
import os
import uuid
import json
from datetime import datetime, timezone
from anthropic import AsyncAnthropicBedrock
from google.cloud import firestore


async def run_extract_batch(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    """Run batch extraction for a spec."""
    config = job.get("config", {})
    spec_id = config.get("spec_id")

    if not spec_id:
        raise ValueError("No spec_id in job config")

    # Load spec
    spec_doc = db.collection(f"workspaces/{workspace_id}/specs").document(spec_id).get()
    if not spec_doc.exists:
        raise ValueError(f"Spec {spec_id} not found")

    spec = spec_doc.to_dict()
    spec_content = spec["specContent"]
    spec_version = spec.get("version", 1)
    print(f"Running batch extraction with spec {spec_id} (v{spec_version})", flush=True)

    # Get documents to process
    doc_col = db.collection(f"workspaces/{workspace_id}/documents")
    scope = config.get("scope", "all_classified")
    if scope == "all_classified":
        docs = list(doc_col.where("status", "in", ["classified", "extracted"]).stream())
    else:
        docs = list(doc_col.where("status", "in", ["classified", "extracted", "enriched"]).stream())

    print(f"Processing {len(docs)} documents", flush=True)

    client = AsyncAnthropicBedrock(
        aws_access_key=os.environ.get("AWS_ACCESS_KEY", ""),
        aws_secret_key=os.environ.get("AWS_SECRET_KEY", ""),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
    )
    extraction_model = os.environ.get("EXTRACTION_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

    total_entities = 0
    chunk_col = db.collection(f"workspaces/{workspace_id}/chunks")
    entity_col = db.collection(f"workspaces/{workspace_id}/entities")
    source_col = db.collection(f"workspaces/{workspace_id}/entitySources")

    for doc_snap in docs:
        doc = doc_snap.to_dict()
        doc_id = doc_snap.id
        content = doc.get("content", "")
        if not content:
            continue

        # Get chunks for this document (client-side sort to avoid composite index)
        chunks = list(chunk_col.where("documentId", "==", doc_id).stream())
        chunks.sort(key=lambda c: c.to_dict().get("chunkIndex", 0))
        if not chunks:
            continue

        # Extract from each chunk
        for chunk_snap in chunks:
            chunk = chunk_snap.to_dict()
            chunk_text = chunk.get("text", "")
            if not chunk_text:
                continue

            try:
                response = await client.messages.create(
                    model=extraction_model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": f"{spec_content}\n\nDocument text:\n{chunk_text}"}],
                )
                text = response.content[0].text
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]

                text = text.strip()
                if text.startswith("["):
                    entities = json.loads(text)
                elif text.startswith("{"):
                    # JSONL format: one object per line
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

                # Check if entity exists
                existing = list(entity_col.where("canonicalName", "==", name).where("type", "==", etype).limit(1).stream())
                if existing:
                    entity_id = existing[0].id
                    # Increment source count
                    entity_col.document(entity_id).update({"sourceCount": firestore.Increment(1)})
                else:
                    entity_id = str(uuid.uuid4())
                    entity_col.document(entity_id).set({
                        "canonicalName": name,
                        "type": etype,
                        "sourceCount": 1,
                        "createdAt": datetime.now(timezone.utc),
                    })

                # Record source
                source_col.add({
                    "entityId": entity_id,
                    "documentId": doc_id,
                    "chunkId": chunk_snap.id,
                    "extractionPass": "batch",
                    "specVersion": spec_version,
                    "jobId": job_id,
                })
                total_entities += 1

        # Update document status
        doc_col.document(doc_id).update({"status": "extracted"})
        print(f"  Processed {doc.get('title', doc_id)}", flush=True)

    # Embed new entities via Vertex AI
    try:
        from google import genai
        project_id = os.environ.get("FIREBASE_PROJECT_ID", "noospheric-orrery")
        region = os.environ.get("VERTEX_AI_REGION", "us-central1")
        ai_client = genai.Client(vertexai=True, project=project_id, location=region)
        from google.cloud.firestore_v1.vector import Vector

        # Find entities without embeddings
        all_entities = list(entity_col.stream())
        to_embed = [(e.id, e.to_dict()["canonicalName"]) for e in all_entities if not e.to_dict().get("embedding")]
        if to_embed:
            print(f"Embedding {len(to_embed)} entities...", flush=True)
            names = [name for _, name in to_embed]
            result = ai_client.models.embed_content(model="text-embedding-004", contents=names)
            for (eid, _), emb in zip(to_embed, result.embeddings):
                entity_col.document(eid).update({"embedding": Vector(emb.values)})
    except Exception as e:
        print(f"Entity embedding failed (non-fatal): {e}", flush=True)

    # Update job result
    job_ref = db.collection(f"workspaces/{workspace_id}/jobs").document(job_id)
    job_ref.update({
        "result": {
            "total_entities": total_entities,
            "documents_processed": len(docs),
        }
    })

    print(f"Batch extraction complete! {total_entities} entities from {len(docs)} docs", flush=True)
