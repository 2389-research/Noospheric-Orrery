"""Migrate existing domain paths to canonical format (lowercase, hyphens).

Renames domains, updates document_domains references, and updates domain layout positions.
Run as Cloud Run Job against production Firestore.
"""
import re
import firebase_admin
from firebase_admin import credentials, firestore as fs


def sanitize(path: str) -> str:
    path = path.lower().strip().strip("/")
    path = path.replace("_", "-")
    path = re.sub(r"[^a-z0-9\-/]", "", path)
    path = re.sub(r"-+", "-", path)
    path = re.sub(r"/+", "/", path)
    path = "/".join(seg.strip("-") for seg in path.split("/") if seg.strip("-"))
    return path


def migrate_workspace(db, ws_id):
    ws_ref = db.collection("workspaces").document(ws_id)
    domains_col = ws_ref.collection("domains")
    layout_col = ws_ref.collection("domainLayout")

    # 1. Find domains that need renaming
    renames = {}  # old_path -> new_path
    for doc in domains_col.stream():
        old_path = doc.to_dict().get("path", doc.id.replace("__", "/"))
        new_path = sanitize(old_path)
        if old_path != new_path:
            renames[old_path] = new_path

    if not renames:
        print(f"  {ws_id}: no domains need renaming")
        return

    print(f"  {ws_id}: {len(renames)} domains to rename")
    for old, new in renames.items():
        print(f"    {old} -> {new}")

    # 2. Rename domains
    for old_path, new_path in renames.items():
        old_encoded = old_path.replace("/", "__")
        new_encoded = new_path.replace("/", "__")

        old_doc = domains_col.document(old_encoded).get()
        if not old_doc.exists:
            continue

        data = old_doc.to_dict()
        data["path"] = new_path
        if data.get("parentPath"):
            data["parentPath"] = sanitize(data["parentPath"])

        # Check if new path already exists (merge doc counts)
        new_doc = domains_col.document(new_encoded).get()
        if new_doc.exists:
            existing = new_doc.to_dict()
            data["documentCount"] = data.get("documentCount", 0) + existing.get("documentCount", 0)

        domains_col.document(new_encoded).set(data)
        if old_encoded != new_encoded:
            domains_col.document(old_encoded).delete()

    # 3. Update document_domains references
    # Documents have domains stored as subcollections: documents/{id}/domains/{encoded_path}
    docs_col = ws_ref.collection("documents")
    for doc in docs_col.stream():
        doc_domains = doc.reference.collection("domains")
        for dd in doc_domains.stream():
            old_path = dd.id.replace("__", "/")
            new_path = sanitize(old_path)
            if old_path != new_path:
                old_encoded = dd.id
                new_encoded = new_path.replace("/", "__")
                dd_data = dd.to_dict()
                if dd_data.get("domainPath"):
                    dd_data["domainPath"] = new_path
                doc_domains.document(new_encoded).set(dd_data)
                if old_encoded != new_encoded:
                    doc_domains.document(old_encoded).delete()

    # 4. Update layout positions
    for old_path, new_path in renames.items():
        old_encoded = old_path.replace("/", "__")
        new_encoded = new_path.replace("/", "__")
        old_layout = layout_col.document(old_encoded).get()
        if old_layout.exists:
            layout_col.document(new_encoded).set(old_layout.to_dict())
            if old_encoded != new_encoded:
                layout_col.document(old_encoded).delete()

    print(f"  {ws_id}: migration complete")


def main():
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred, {"projectId": "noospheric-orrery"})
    db = fs.Client(project="noospheric-orrery")

    for ws in db.collection("workspaces").stream():
        migrate_workspace(db, ws.id)

    print("Done!")


if __name__ == "__main__":
    main()
