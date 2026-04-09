"""Post-extraction processing pipeline.

Shared by batch extraction and any other path that adds entities.
Runs: embed → cooccurrences → UMAP layout → graph cache.
"""
import os
import json
import math
from google.cloud import firestore


def run_post_processing(db: firestore.Client, workspace_id: str):
    """Run all post-extraction steps. Idempotent — safe to call multiple times."""

    entity_col = db.collection(f"workspaces/{workspace_id}/entities")
    source_col = db.collection(f"workspaces/{workspace_id}/entitySources")

    # ── 1. Embed entities (Vertex AI, batched) ────────────────────
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
        else:
            print("  All entities already embedded", flush=True)
    except Exception as e:
        print(f"Entity embedding failed (non-fatal): {e}", flush=True)

    # ── 2. Compute cooccurrences ──────────────────────────────────
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

    # ── 3. Compute domain layout (UMAP transform) ─────────────────
    try:
        print("Computing UMAP domain layout...", flush=True)
        import pickle
        import numpy as np

        domain_col = db.collection(f"workspaces/{workspace_id}/domains")
        layout_col = db.collection(f"workspaces/{workspace_id}/domainLayout")

        all_domains = list(domain_col.stream())
        domain_paths = [d.to_dict().get("path", "") for d in all_domains if d.to_dict().get("path")]

        # Find domains that don't have positions yet
        stored = {d.id.replace("__", "/"): d.to_dict() for d in layout_col.stream()}
        missing = [p for p in domain_paths if p not in stored]

        if not missing:
            print(f"  All {len(domain_paths)} domains already have positions", flush=True)
        else:
            # Load the universal UMAP model (stored in default workspace)
            model_doc = db.collection("workspaces/default/layoutModel/umap").get()
            if not model_doc.exists:
                # Try this workspace
                model_doc = db.collection(f"workspaces/{workspace_id}/layoutModel/umap").get()

            if model_doc.exists and model_doc.to_dict().get("modelBlob"):
                model_data = pickle.loads(model_doc.to_dict()["modelBlob"])
                reducer = model_data["reducer"]
                mins, ranges = model_data["mins"], model_data["ranges"]

                # Embed domain names with sentence-transformers (same model used to train UMAP)
                from sentence_transformers import SentenceTransformer
                embed_model = SentenceTransformer("all-MiniLM-L6-v2")
                texts = [p.replace("/", " ").replace("-", " ") for p in missing]
                embeddings = embed_model.encode(texts, normalize_embeddings=True)

                coords = reducer.transform(embeddings)
                for i, path in enumerate(missing):
                    x = float(np.clip((coords[i, 0] - mins[0]) / ranges[0], 0, 1))
                    y = float(np.clip((coords[i, 1] - mins[1]) / ranges[1], 0, 1))
                    layout_col.document(path.replace("/", "__")).set({"x": x, "y": y})

                print(f"  Positioned {len(missing)} new domains via UMAP transform", flush=True)
            else:
                print(f"  No UMAP model found — {len(missing)} domains without positions", flush=True)
    except Exception as e:
        print(f"Domain layout failed (non-fatal): {e}", flush=True)

    # ── 4. Build and cache graph JSON ─────────────────────────────
    try:
        print("Building graph cache...", flush=True)
        _build_graph_cache(db, workspace_id)
        print("  Graph cached", flush=True)
    except Exception as e:
        print(f"Graph cache failed (non-fatal): {e}", flush=True)


def _build_graph_cache(db: firestore.Client, workspace_id: str):
    """Precompute the full graph JSON and store as a single Firestore doc."""

    domains_raw = list(db.collection(f"workspaces/{workspace_id}/domains").stream())
    layout_raw = list(db.collection(f"workspaces/{workspace_id}/domainLayout").stream())
    sources_raw = list(db.collection(f"workspaces/{workspace_id}/entitySources").stream())
    doc_domains_raw = list(db.collection(f"workspaces/{workspace_id}/documentDomains").stream())
    entities_raw = list(db.collection(f"workspaces/{workspace_id}/entities").stream())
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

    doc_to_domains = {}
    for dd in doc_domains_raw:
        ddd = dd.to_dict()
        doc_to_domains.setdefault(ddd.get("documentId", ""), []).append(ddd.get("domainPath", ""))

    domain_video_counts = {d.to_dict().get("path", ""): d.to_dict().get("documentCount", 0) for d in domains_raw}

    # Only domain-specific specs count
    domain_spec_paths = {s.to_dict().get("domainPath") for s in specs_raw if s.to_dict().get("domainPath")}
    domain_specs = {
        d.to_dict().get("path", ""): ({"spec_version": 1} if d.to_dict().get("path", "") in domain_spec_paths else None)
        for d in domains_raw
    }

    regions = sorted(set(d.to_dict().get("path", "").split("/")[0] for d in domains_raw))
    hues = [200, 280, 120, 40, 340, 60, 180, 300]
    region_colors = {r: f"hsl({hues[i % len(hues)]}, 70%, 60%)" for i, r in enumerate(regions)}

    subdomains = [d.to_dict().get("path", "") for d in domains_raw if d.to_dict().get("path", "").count("/") >= 2]

    # Entity domain weights
    entity_weights: dict[str, dict[str, float]] = {}
    for s in sources_raw:
        sd = s.to_dict()
        eid, did = sd.get("entityId", ""), sd.get("documentId", "")
        if eid and did:
            for path in doc_to_domains.get(did, []):
                entity_weights.setdefault(eid, {})[path] = entity_weights.get(eid, {}).get(path, 0) + 1
    for eid, counts in entity_weights.items():
        total = sum(counts.values())
        entity_weights[eid] = {p: round(c / total, 3) for p, c in counts.items()}

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

    # Trade routes — domain-to-domain
    domain_cooccur: dict[tuple[str, str], int] = {}
    for dw in entity_weights.values():
        paths = list(dw.keys())
        for i in range(len(paths)):
            for j in range(i + 1, len(paths)):
                pair = tuple(sorted([paths[i], paths[j]]))
                domain_cooccur[pair] = domain_cooccur.get(pair, 0) + 1
    trade_routes = [{"source": p[0], "target": p[1], "weight": w}
                    for p, w in sorted(domain_cooccur.items(), key=lambda x: -x[1])[:200]]

    videos = [{"id": d.id, "title": d.to_dict().get("title", ""),
               "domains": doc_to_domains.get(d.id, []),
               "primary": doc_to_domains.get(d.id, [None])[0]} for d in docs_raw[:50]]

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
    if len(graph_json) < 900000:
        db.collection(f"workspaces/{workspace_id}/cache").document("graph").set({
            "data": graph_json, "updatedAt": firestore.SERVER_TIMESTAMP,
        })
