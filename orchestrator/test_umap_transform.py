import pickle, numpy as np, platform, sys, numba
print(f"arch: {platform.machine()}, python: {sys.version}, numba: {numba.__version__}")

import firebase_admin
from firebase_admin import credentials, firestore as fs
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred, {"projectId": "noospheric-orrery"})
db = fs.Client(project="noospheric-orrery")

doc = db.collection("workspaces").document("default").collection("layoutModel").document("umap").get()
data = pickle.loads(doc.to_dict()["modelBlob"])
print(f"Model loaded: {doc.to_dict()['domainCount']} domains")

from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")

domains = [
    "business/fundraising/venture-capital",
    "hobbies/miniature-wargaming/painted-miniatures",
    "science/quantum-computing/error-correction",
]
texts = [d.replace("/", " ").replace("-", " ") for d in domains]
embeddings = model.encode(texts, normalize_embeddings=True)

coords = data["reducer"].transform(embeddings)
for i, d in enumerate(domains):
    x = float(np.clip((coords[i, 0] - data["mins"][0]) / data["ranges"][0], 0, 1))
    y = float(np.clip((coords[i, 1] - data["mins"][1]) / data["ranges"][1], 0, 1))
    print(f"  {d}: x={x:.3f} y={y:.3f}")
print("transform() SUCCESS")
