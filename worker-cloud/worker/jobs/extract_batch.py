"""Batch entity extraction from documents using a simmered spec.

Post-extraction pipeline:
  1. Extract entities from chunks via Haiku
  2. Embed entities (Vertex AI text-embedding-004, batched)
  3. Compute entity cooccurrences
  4. Compute domain layout (UMAP from Vertex AI embeddings)
  5. Build and cache graph JSON for the orrery
"""
import os
import uuid
import json
import math
from datetime import datetime, timezone
from google.cloud import firestore


async def run_extract_batch(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    """Run batch extraction with full post-processing pipeline."""
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
        # Use general spec
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

    # Get documents to process
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

    # ── Stage 1: Extract entities from chunks ─────────────────────
    print(f"Processing {len(docs)} documents", flush=True)

    for doc_snap in docs:
        doc = doc_snap.to_dict()
        doc_id = doc_snap.id
        if not doc.get("content"):
            continue

        # Get chunks (client-side sort to avoid composite index)
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

    # ── Stage 2: Embed entities (Vertex AI, batched) ──────────────
    try:
        from google import genai
        from google.cloud.firestore_v1.vector import Vector

        project_id = os.environ.get("FIREBASE_PROJECT_ID", "noospheric-orrery")
        region = os.environ.get("VERTEX_AI_REGION", "us-central1")
        ai_client = genai.Client(vertexai=True, project=project_id, location=region)

        all_entities = list(entity_col.stream())
        to_embed = [(e.id, e.to_dict()["canonicalName"]) for e in all_entities if not e.to_dict().get("embedding")]

        if to_embed:
            print(f"Embedding {len(to_embed)} entities...", flush=True)
            batch_size = 100
            for i in range(0, len(to_embed), batch_size):
                batch = to_embed[i:i + batch_size]
                names = [name for _, name in batch]
                result = ai_client.models.embed_content(model="text-embedding-004", contents=names)
                for (eid, _), emb in zip(batch, result.embeddings):
                    entity_col.document(eid).update({"embedding": Vector(emb.values)})
                print(f"  Embedded {min(i + batch_size, len(to_embed))}/{len(to_embed)}", flush=True)
    except Exception as e:
        print(f"Entity embedding failed (non-fatal): {e}", flush=True)

    # ── Stage 3: Compute cooccurrences ────────────────────────────
    try:
        print("Computing cooccurrences...", flush=True)
        rel_col = db.collection(f"workspaces/{workspace_id}/relationships")

        all_sources = list(source_col.stream())
        doc_entities: dict[str, set[str]] = {}
        for s in all_sources:
            sd = s.to_dict()
            did, eid = sd.get("documentId", ""), sd.get("entityId", "")
            if did and eid:
                doc_entities.setdefault(did, set()).add(eid)

        cooccurrence_counts: dict[tuple[str, str], int] = {}
        for eids in doc_entities.values():
            eid_list = sorted(eids)
            for i in range(len(eid_list)):
                for j in range(i + 1, len(eid_list)):
                    pair = (eid_list[i], eid_list[j])
                    cooccurrence_counts[pair] = cooccurrence_counts.get(pair, 0) + 1

        top_pairs = sorted(cooccurrence_counts.items(), key=lambda x: -x[1])[:500]
        for (ea, eb), weight in top_pairs:
            rel_col.document(f"{ea}_{eb}").set({
                "entityA": ea, "entityB": eb, "weight": weight, "type": "cooccurrence",
            })
        print(f"  Stored {len(top_pairs)} cooccurrence relationships", flush=True)
    except Exception as e:
        print(f"Cooccurrence computation failed (non-fatal): {e}", flush=True)

    # ── Stage 4: Compute domain layout (UMAP) ────────────────────
    try:
        print("Computing UMAP domain layout...", flush=True)
        import numpy as np

        domain_col = db.collection(f"workspaces/{workspace_id}/domains")
        layout_col = db.collection(f"workspaces/{workspace_id}/domainLayout")
        all_domains = list(domain_col.stream())
        docs_raw = list(doc_col.stream())
        doc_domains_raw = list(db.collection(f"workspaces/{workspace_id}/documentDomains").stream())

        # Build domain -> entities and domain -> doc titles
        doc_to_domains = {}
        for dd in doc_domains_raw:
            ddd = dd.to_dict()
            doc_to_domains.setdefault(ddd.get("documentId", ""), []).append(ddd.get("domainPath", ""))

        domain_entity_names = {}
        ename = {e.id: e.to_dict().get("canonicalName", "") for e in all_entities}
        for s in all_sources:
            sd = s.to_dict()
            for path in doc_to_domains.get(sd.get("documentId", ""), []):
                domain_entity_names.setdefault(path, set()).add(ename.get(sd.get("entityId", ""), ""))

        doc_titles = {}
        for d in docs_raw:
            for path in doc_to_domains.get(d.id, []):
                doc_titles.setdefault(path, []).append(d.to_dict().get("title", ""))

        # Build embedding text per domain
        domain_texts, domain_paths = [], []
        for d in all_domains:
            path = d.to_dict().get("path", "")
            ents = sorted(domain_entity_names.get(path, set()))[:10]
            titles = doc_titles.get(path, [])[:5]
            text = f'{path.replace("/", " > ")}. Documents: {", ".join(titles)}. Entities: {", ".join(ents)}'
            domain_texts.append(text)
            domain_paths.append(path)

        if len(domain_texts) >= 3:
            # Embed and UMAP
            result = ai_client.models.embed_content(model="text-embedding-004", contents=domain_texts)
            embeddings = np.array([e.values for e in result.embeddings])

            import umap
            reducer = umap.UMAP(n_components=2, n_neighbors=min(5, len(domain_paths) - 1), min_dist=0.3, random_state=42)
            positions = reducer.fit_transform(embeddings)

            # Normalize to -400..400
            positions -= positions.min(axis=0)
            scale = positions.max(axis=0)
            scale[scale == 0] = 1
            positions = (positions / scale) * 800 - 400

            for i, path in enumerate(domain_paths):
                layout_col.document(path.replace("/", "__")).set({
                    "x": float(positions[i][0]), "y": float(positions[i][1]),
                })
            print(f"  UMAP layout for {len(domain_paths)} domains", flush=True)
        else:
            # Too few domains for UMAP — simple circle
            for i, path in enumerate(domain_paths):
                angle = (2 * math.pi * i) / max(len(domain_paths), 1)
                layout_col.document(path.replace("/", "__")).set({
                    "x": math.cos(angle) * 300, "y": math.sin(angle) * 300,
                })
            print(f"  Circular layout for {len(domain_paths)} domains (too few for UMAP)", flush=True)
    except Exception as e:
        print(f"Domain layout failed (non-fatal): {e}", flush=True)

    # ── Stage 5: Build and cache graph JSON ───────────────────────
    try:
        print("Building graph cache...", flush=True)
        _build_graph_cache(db, workspace_id)
        print("  Graph cached", flush=True)
    except Exception as e:
        print(f"Graph cache failed (non-fatal): {e}", flush=True)

    # ── Update job result ─────────────────────────────────────────
    db.collection(f"workspaces/{workspace_id}/jobs").document(job_id).update({
        "result": {"total_entities": total_entities, "documents_processed": len(docs)},
    })
    print(f"Batch extraction complete! {total_entities} entities from {len(docs)} docs", flush=True)


def _build_graph_cache(db: firestore.Client, workspace_id: str):
    """Precompute the full graph JSON and store as a single Firestore doc."""

    domains_raw = list(db.collection(f"workspaces/{workspace_id}/domains").stream())
    layout_raw = list(db.collection(f"workspaces/{workspace_id}/domainLayout").stream())
    sources_raw = list(db.collection(f"workspaces/{workspace_id}/entitySources").stream())
    doc_domains_raw = list(db.collection(f"workspaces/{workspace_id}/documentDomains").stream())
    entities_raw = list(db.collection(f"workspaces/{workspace_id}/entities").stream())
    rels_raw = list(db.collection(f"workspaces/{workspace_id}/relationships").stream())
    docs_raw = list(db.collection(f"workspaces/{workspace_id}/documents").stream())
    specs_raw = list(db.collection(f"workspaces/{workspace_id}/specs").stream())
    jobs_raw = list(db.collection(f"workspaces/{workspace_id}/jobs").stream())

    # Domain positions — normalized 0-1
    layout_map = {l.id.replace("__", "/"): l.to_dict() for l in layout_raw}
    if layout_map:
        xs = [v["x"] for v in layout_map.values()]
        ys = [v["y"] for v in layout_map.values()]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        rx, ry = (max_x - min_x) or 1, (max_y - min_y) or 1
        domain_positions = {p: {"x": (v["x"] - min_x) / rx, "y": (v["y"] - min_y) / ry} for p, v in layout_map.items()}
    else:
        domain_positions = {}

    # Doc -> domains
    doc_to_domains = {}
    for dd in doc_domains_raw:
        ddd = dd.to_dict()
        doc_to_domains.setdefault(ddd.get("documentId", ""), []).append(ddd.get("domainPath", ""))

    # Domain video counts
    domain_video_counts = {d.to_dict().get("path", ""): d.to_dict().get("documentCount", 0) for d in domains_raw}

    # Domain specs — only domain-specific specs, not general
    domain_spec_paths = {s.to_dict().get("domainPath") for s in specs_raw if s.to_dict().get("domainPath")}
    domain_specs = {d.to_dict().get("path", ""): ({"spec_version": 1} if d.to_dict().get("path", "") in domain_spec_paths else None) for d in domains_raw}

    # Region colors
    regions = sorted(set(d.to_dict().get("path", "").split("/")[0] for d in domains_raw))
    hues = [200, 280, 120, 40, 340, 60, 180, 300]
    region_colors = {r: f"hsl({hues[i % len(hues)]}, 70%, 60%)" for i, r in enumerate(regions)}

    # Subdomains
    subdomains = [d.to_dict().get("path", "") for d in domains_raw if d.to_dict().get("path", "").count("/") >= 2]

    # Entity domain weights
    entity_weights = {}
    for s in sources_raw:
        sd = s.to_dict()
        eid, did = sd.get("entityId", ""), sd.get("documentId", "")
        if eid and did:
            for path in doc_to_domains.get(did, []):
                entity_weights.setdefault(eid, {})[path] = entity_weights.get(eid, {}).get(path, 0) + 1
    for eid, counts in entity_weights.items():
        total = sum(counts.values())
        entity_weights[eid] = {p: round(c / total, 3) for p, c in counts.items()}

    # Entities
    entities = []
    for e in entities_raw:
        ed = e.to_dict()
        dw = entity_weights.get(e.id, {})
        if not dw:
            continue
        entities.append({
            "entityId": e.id, "name": ed.get("canonicalName", ""),
            "type": ed.get("type", "Thing"), "videoCount": ed.get("sourceCount", 0),
            "domainWeights": dw,
        })

    # Trade routes — domain-to-domain from shared entities
    domain_cooccur = {}
    for dw in entity_weights.values():
        paths = list(dw.keys())
        for i in range(len(paths)):
            for j in range(i + 1, len(paths)):
                pair = tuple(sorted([paths[i], paths[j]]))
                domain_cooccur[pair] = domain_cooccur.get(pair, 0) + 1
    trade_routes = [{"source": p[0], "target": p[1], "weight": w}
                    for p, w in sorted(domain_cooccur.items(), key=lambda x: -x[1])[:200]]

    # Videos
    videos = [{"id": d.id, "title": d.to_dict().get("title", ""),
               "domains": doc_to_domains.get(d.id, []),
               "primary": doc_to_domains.get(d.id, [None])[0]} for d in docs_raw[:50]]

    # Active simmers
    active_simmers = [j.to_dict().get("target", "") for j in jobs_raw
                      if j.to_dict().get("type", "").startswith("simmer") and j.to_dict().get("status") == "running"]

    graph = {
        "domain_positions": domain_positions,
        "domain_video_counts": domain_video_counts,
        "domain_specs": domain_specs,
        "active_simmers": active_simmers,
        "region_colors": region_colors,
        "subdomains": subdomains,
        "videos": videos,
        "entities": entities,
        "v3_entities": [],
        "trade_routes": trade_routes,
    }

    graph_json = json.dumps(graph)
    if len(graph_json) < 900000:  # Firestore doc limit ~1MB
        db.collection(f"workspaces/{workspace_id}/cache").document("graph").set({
            "data": graph_json, "updatedAt": firestore.SERVER_TIMESTAMP,
        })
