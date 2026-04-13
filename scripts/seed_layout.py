"""Pull UMAP layout from production Firestore and push to emulator.

Usage (from inside orchestrator container with ADC mounted):
  python scripts/seed_layout.py <target_workspace_id>
"""
import os
import sys

TARGET_WS = sys.argv[1] if len(sys.argv) > 1 else None

# 1. Connect to production (no emulator)
emulator_host = os.environ.pop("FIRESTORE_EMULATOR_HOST", None)

import firebase_admin
from firebase_admin import credentials, firestore as fs

cred = credentials.ApplicationDefault()
prod_app = firebase_admin.initialize_app(cred, {"projectId": "noospheric-orrery"}, name="prod")
prod_db = fs.Client(project="noospheric-orrery")

# Find source workspace with layout
source_ws = None
for ws in prod_db.collection("workspaces").stream():
    layout_docs = list(prod_db.collection("workspaces").document(ws.id).collection("domainLayout").limit(1).stream())
    if layout_docs:
        source_ws = ws.id
        break

if not source_ws:
    print("No workspace with layout data found in production")
    sys.exit(1)

# Read positions
positions = {}
for doc in prod_db.collection("workspaces").document(source_ws).collection("domainLayout").stream():
    positions[doc.id] = doc.to_dict()
print(f"Read {len(positions)} domain positions from production workspace {source_ws}")

# Read UMAP model
model_ref = prod_db.collection("workspaces").document(source_ws).collection("layoutModel").document("umap")
model_doc = model_ref.get()
model_data = model_doc.to_dict() if model_doc.exists else None
if model_data:
    print(f"Read UMAP model: domain_count={model_data.get('domainCount')}")
else:
    print("No UMAP model found")

firebase_admin.delete_app(prod_app)

# 2. Connect to emulator
if emulator_host:
    os.environ["FIRESTORE_EMULATOR_HOST"] = emulator_host

emu_app = firebase_admin.initialize_app(
    firebase_admin.credentials.ApplicationDefault() if not emulator_host else None,
    {"projectId": "noospheric-orrery"},
    name="emu",
)
emu_db = fs.Client(project="noospheric-orrery")

if not TARGET_WS:
    # Find first workspace in emulator
    for ws in emu_db.collection("workspaces").stream():
        TARGET_WS = ws.id
        break

if not TARGET_WS:
    print("No target workspace found in emulator")
    sys.exit(1)

print(f"Writing to emulator workspace {TARGET_WS}")

# Write positions
batch = emu_db.batch()
for doc_id, data in positions.items():
    ref = emu_db.collection("workspaces").document(TARGET_WS).collection("domainLayout").document(doc_id)
    batch.set(ref, data)
batch.commit()
print(f"Wrote {len(positions)} domain positions")

# Write model
if model_data:
    emu_db.collection("workspaces").document(TARGET_WS).collection("layoutModel").document("umap").set(model_data)
    print("Wrote UMAP model")

print("Done!")
