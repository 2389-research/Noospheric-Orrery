"""Fix documentDomains paths to match migrated domain format."""
import re
import firebase_admin
from firebase_admin import credentials, firestore as fs
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred, {"projectId": "noospheric-orrery"})
db = fs.Client(project="noospheric-orrery")

def sanitize(path):
    path = path.lower().strip().strip("/")
    path = path.replace("_", "-")
    path = re.sub(r"[^a-z0-9\-/]", "", path)
    path = re.sub(r"-+", "-", path)
    path = re.sub(r"/+", "/", path)
    path = "/".join(seg.strip("-") for seg in path.split("/") if seg.strip("-"))
    return path

for ws in db.collection("workspaces").stream():
    ws_id = ws.id
    dd_col = db.collection(f"workspaces/{ws_id}/documentDomains")
    fixed = 0
    for dd in dd_col.stream():
        d = dd.to_dict()
        old_path = d.get("domainPath", "")
        new_path = sanitize(old_path)
        if old_path != new_path:
            dd.reference.update({"domainPath": new_path})
            fixed += 1
    if fixed:
        print(f"{ws_id}: fixed {fixed} documentDomain paths")
    
    # Also clear graph cache
    cache = db.collection(f"workspaces/{ws_id}/cache").document("graph")
    if cache.get().exists:
        cache.delete()
        print(f"{ws_id}: cleared cache")

print("Done")
