"""Fit a universal UMAP model from the domain corpus and store to Firestore.

Loads: orchestrator/specs/universal_domains.json (baked into Docker image)
Stores: Firestore workspaces/default/layoutModel/umap + training-domains

Run as Cloud Run Job on x86 (numba JIT required for transform test).
"""
import json
import pickle
import numpy as np
import sys
import os

def main():
    import platform, numba
    print(f"arch: {platform.machine()}, python: {sys.version}, numba: {numba.__version__}")

    # Load domain corpus
    corpus_path = os.environ.get("CORPUS_PATH", "/app/orchestrator/specs/universal_domains.json")
    with open(corpus_path) as f:
        corpus = json.load(f)
    domains = corpus["domains"]
    print(f"Loaded {len(domains)} training domains")

    # Embed
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    texts = [d.replace("/", " ").replace("-", " ") for d in domains]
    embeddings = model.encode(texts, normalize_embeddings=True)
    print(f"Embedded, shape: {embeddings.shape}")

    # Fit UMAP
    import umap
    n_neighbors = min(15, len(domains) - 1)
    reducer = umap.UMAP(
        n_components=2, n_neighbors=n_neighbors,
        min_dist=0.15, spread=2.5, metric="cosine", random_state=42,
    )
    coords = reducer.fit_transform(embeddings)
    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1
    print(f"UMAP fit complete")

    # Test transform on held-out domains
    test_domains = [
        "cooking/french/pastry-techniques",
        "business/venture-capital/due-diligence",
        "science/astrophysics/black-holes",
        "hobbies/warhammer/army-painting",
        "technology/blockchain/smart-contracts",
    ]
    test_texts = [d.replace("/", " ").replace("-", " ") for d in test_domains]
    test_embeddings = model.encode(test_texts, normalize_embeddings=True)
    test_coords = reducer.transform(test_embeddings)
    print("\nTransform test (held-out domains):")
    for i, d in enumerate(test_domains):
        x = float(np.clip((test_coords[i, 0] - mins[0]) / ranges[0], 0, 1))
        y = float(np.clip((test_coords[i, 1] - mins[1]) / ranges[1], 0, 1))
        print(f"  {d}: x={x:.3f} y={y:.3f}")

    # Pickle test
    model_data = {"reducer": reducer, "mins": mins, "maxs": maxs, "ranges": ranges}
    blob = pickle.dumps(model_data)
    data2 = pickle.loads(blob)
    test_coords2 = data2["reducer"].transform(test_embeddings)
    print(f"\nPickle round-trip test:")
    print(f"  Blob size: {len(blob)} bytes")
    print(f"  Coords match: {np.allclose(test_coords, test_coords2)}")

    # Store to Firestore
    import firebase_admin
    from firebase_admin import credentials, firestore as fs
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred, {"projectId": "noospheric-orrery"})
    db = fs.Client(project="noospheric-orrery")

    # Store to default workspace
    ws_id = os.environ.get("TARGET_WORKSPACE", "default")
    ws_ref = db.collection("workspaces").document(ws_id)

    # Store model
    ws_ref.collection("layoutModel").document("umap").set({
        "modelBlob": blob,
        "domainCount": len(domains),
        "numbaVersion": numba.__version__,
        "pythonVersion": sys.version,
        "createdAt": fs.SERVER_TIMESTAMP,
    })
    print(f"\nStored UMAP model to workspaces/{ws_id}/layoutModel/umap")

    # Store training domain list
    ws_ref.collection("layoutModel").document("training-domains").set({
        "domains": domains,
        "count": len(domains),
        "categories": corpus.get("categories", []),
        "createdAt": fs.SERVER_TIMESTAMP,
    })

    # Store positions for training domains
    batch = db.batch()
    for i, domain in enumerate(domains):
        x = float((coords[i, 0] - mins[0]) / ranges[0])
        y = float((coords[i, 1] - mins[1]) / ranges[1])
        encoded = domain.replace("/", "__")
        ref = ws_ref.collection("domainLayout").document(encoded)
        batch.set(ref, {"x": x, "y": y, "embedding": embeddings[i].tobytes()})
    batch.commit()
    print(f"Stored {len(domains)} training domain positions")

    print(f"\nDone! Universal UMAP model trained on {len(domains)} domains.")


if __name__ == "__main__":
    main()
