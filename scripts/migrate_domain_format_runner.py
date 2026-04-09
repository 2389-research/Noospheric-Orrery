import pickle, numpy as np, json, sys

import firebase_admin
from firebase_admin import credentials, firestore as fs
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred, {"projectId": "noospheric-orrery"})
db = fs.Client(project="noospheric-orrery")

doc = db.collection("workspaces").document("default").collection("layoutModel").document("umap").get()
model_data = pickle.loads(doc.to_dict()["modelBlob"])
reducer = model_data["reducer"]
mins, ranges = model_data["mins"], model_data["ranges"]

from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")

domains = [
    "business/finance/fundraising",
    "business/finance/venture_capital",
    "business/networking/investor_relations",
    "entertainment/games/warhammer_40k",
    "hobbies/crafts/scale_modeling",
    "hobbies/tabletop_gaming/miniature_painting",
    "hobbies/tabletop_gaming/wargaming",
]

texts = [d.replace("/", " ").replace("_", " ") for d in domains]
embeddings = model.encode(texts, normalize_embeddings=True)
coords = reducer.transform(embeddings)

positions = {}
for i, d in enumerate(domains):
    x = float(np.clip((coords[i, 0] - mins[0]) / ranges[0], 0, 1))
    y = float(np.clip((coords[i, 1] - mins[1]) / ranges[1], 0, 1))
    positions[d] = {"x": x, "y": y}
    print(f"  {d}: x={x:.3f} y={y:.3f}")

print(f"POSITIONS:{json.dumps(positions)}")
