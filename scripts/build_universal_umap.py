"""Build a universal UMAP model from a broad set of generated domain names.

1. Generate ~100 diverse domain paths via Sonnet (10 calls x 10 domains)
2. Embed with sentence-transformers
3. Fit UMAP
4. Store model + domain list to Firestore
5. Test transform() on held-out domains

Usage (as Cloud Run Job):
  python scripts/build_universal_umap.py

Requires: ANTHROPIC_BACKEND, AWS_ACCESS_KEY, AWS_SECRET_KEY (for Bedrock Sonnet calls)
          or GOOGLE_APPLICATION_CREDENTIALS (for Firestore)
"""
import json
import pickle
import numpy as np
import sys
import os

# -- Step 1: Generate diverse domains via Sonnet --

CATEGORIES = [
    "business and finance (startups, fundraising, operations, marketing, strategy, consulting, real estate, accounting)",
    "science and research (physics, chemistry, biology, neuroscience, ecology, astronomy, geology, materials science)",
    "technology and engineering (AI/ML, web development, mobile, DevOps, robotics, embedded systems, security, databases)",
    "arts and creative (painting, music, film, photography, sculpture, writing, theater, graphic design)",
    "hobbies and crafts (miniature painting, woodworking, gardening, cooking, brewing, sewing, model building, ceramics)",
    "health and medicine (cardiology, oncology, mental health, nutrition, physical therapy, epidemiology, genomics)",
    "education and academia (pedagogy, curriculum design, educational technology, student assessment, research methodology)",
    "sports and fitness (basketball, climbing, swimming, martial arts, cycling, yoga, track and field)",
    "history and humanities (ancient history, philosophy, linguistics, archaeology, anthropology, religious studies)",
    "environment and sustainability (renewable energy, conservation, urban planning, waste management, climate science)",
]


def generate_domains_batch(relay, category, n=10):
    """Ask Sonnet to generate n domain paths for a category."""
    import asyncio

    prompt = f"""Generate exactly {n} domain classification paths for documents about: {category}

Each path should be 3 levels deep using / as separator, lowercase with hyphens.
Format: one path per line, nothing else.

Example format:
business/fundraising/seed-rounds
science/physics/quantum-mechanics
hobbies/miniature-painting/wet-blending

Be specific and diverse within the category. No duplicates. No numbering."""

    async def _call():
        response = await relay.complete(
            model=os.environ.get("CLASSIFICATION_MODEL", "claude-sonnet-4-6"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        return response.text

    text = asyncio.get_event_loop().run_until_complete(_call())
    paths = [line.strip() for line in text.strip().split("\n") if "/" in line and len(line.strip()) > 5]
    return paths[:n]


def main():
    print(f"arch: {__import__('platform').machine()}, python: {sys.version}")
    import numba
    print(f"numba: {numba.__version__}")

    # Setup relay for Sonnet calls
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator", "src"))
    from orrery_relay import Relay

    class FakeSettings:
        anthropic_backend = os.environ.get("ANTHROPIC_BACKEND", "bedrock")
        gateway_url = os.environ.get("GATEWAY_URL", "")
        aws_access_key = os.environ.get("AWS_ACCESS_KEY", "")
        aws_secret_key = os.environ.get("AWS_SECRET_KEY", "")
        aws_region = os.environ.get("AWS_REGION", "us-east-1")
        ollama_url = os.environ.get("OLLAMA_URL", "")

    relay = Relay.from_settings(FakeSettings())

    # Generate domains
    all_domains = []
    for i, category in enumerate(CATEGORIES):
        print(f"Generating batch {i+1}/{len(CATEGORIES)}: {category[:40]}...")
        try:
            domains = generate_domains_batch(relay, category, n=10)
            all_domains.extend(domains)
            print(f"  Got {len(domains)} domains")
        except Exception as e:
            print(f"  Failed: {e}")

    # Deduplicate
    all_domains = list(dict.fromkeys(all_domains))
    print(f"\nTotal unique domains: {len(all_domains)}")

    # -- Step 2: Embed with sentence-transformers --
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")

    texts = [d.replace("/", " ").replace("-", " ") for d in all_domains]
    embeddings = model.encode(texts, normalize_embeddings=True)
    print(f"Embedded {len(embeddings)} domains, shape: {embeddings.shape}")

    # -- Step 3: Fit UMAP --
    import umap
    n_neighbors = min(15, len(all_domains) - 1)
    reducer = umap.UMAP(
        n_components=2, n_neighbors=n_neighbors,
        min_dist=0.15, spread=2.5, metric="cosine", random_state=42,
    )
    coords = reducer.fit_transform(embeddings)
    print(f"UMAP fit complete, coords shape: {coords.shape}")

    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1

    # -- Step 4: Test transform on held-out domains --
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
    print("\nTransform test on held-out domains:")
    for i, d in enumerate(test_domains):
        x = float(np.clip((test_coords[i, 0] - mins[0]) / ranges[0], 0, 1))
        y = float(np.clip((test_coords[i, 1] - mins[1]) / ranges[1], 0, 1))
        print(f"  {d}: x={x:.3f} y={y:.3f}")
    print("transform() SUCCESS")

    # -- Step 5: Store to Firestore --
    model_data = {"reducer": reducer, "mins": mins, "maxs": maxs, "ranges": ranges}
    model_blob = pickle.dumps(model_data)
    print(f"\nModel blob: {len(model_blob)} bytes")

    import firebase_admin
    from firebase_admin import credentials, firestore as fs

    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred, {"projectId": "noospheric-orrery"})
    db = fs.Client(project="noospheric-orrery")

    # Store model to default workspace
    db.collection("workspaces").document("default").collection("layoutModel").document("umap").set({
        "modelBlob": model_blob,
        "domainCount": len(all_domains),
        "trainDomains": all_domains,
        "numbaVersion": numba.__version__,
        "pythonVersion": sys.version,
        "createdAt": fs.SERVER_TIMESTAMP,
    })
    print(f"Stored model to Firestore (default workspace)")

    # Store domain list as a reference document
    db.collection("workspaces").document("default").collection("layoutModel").document("training-domains").set({
        "domains": all_domains,
        "count": len(all_domains),
        "createdAt": fs.SERVER_TIMESTAMP,
    })
    print(f"Stored {len(all_domains)} training domains")

    # Also store positions for the training domains
    batch = db.batch()
    for i, domain in enumerate(all_domains):
        x = float((coords[i, 0] - mins[0]) / ranges[0])
        y = float((coords[i, 1] - mins[1]) / ranges[1])
        encoded = domain.replace("/", "__")
        ref = db.collection("workspaces").document("default").collection("domainLayout").document(encoded)
        batch.set(ref, {"x": x, "y": y, "embedding": embeddings[i].tobytes()})
    batch.commit()
    print(f"Stored {len(all_domains)} domain positions")

    # Save domain list locally too
    with open("/tmp/universal_umap_domains.json", "w") as f:
        json.dump({"domains": all_domains, "count": len(all_domains)}, f, indent=2)
    print(f"\nDone! Model trained on {len(all_domains)} domains, stored to Firestore.")


if __name__ == "__main__":
    main()
