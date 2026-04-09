import re
import uuid


def _sanitize_domain_path(path: str) -> str:
    """Normalize a domain path to canonical format: lowercase, hyphens, no special chars."""
    path = path.lower().strip().strip("/")
    # Replace underscores with hyphens
    path = path.replace("_", "-")
    # Remove anything that isn't a-z, 0-9, hyphen, or /
    path = re.sub(r"[^a-z0-9\-/]", "", path)
    # Collapse multiple hyphens or slashes
    path = re.sub(r"-+", "-", path)
    path = re.sub(r"/+", "/", path)
    # Strip leading/trailing hyphens from each segment
    path = "/".join(seg.strip("-") for seg in path.split("/") if seg.strip("-"))
    return path


def normalize_domain_label(store_or_conn, label: str) -> str:
    """Check merge map, then insert as new domain if not found.

    Accepts either a DataStore or raw sqlite3.Connection.
    """
    label = _sanitize_domain_path(label)
    if hasattr(store_or_conn, 'domains'):
        store = store_or_conn
        target = store.domains.get_merge_target(label)
        if target:
            return target
        existing = store.domains.get(label)
        if existing:
            return existing.path
        parent_path = "/".join(label.split("/")[:-1]) or None
        store.domains.create(str(uuid.uuid4()), label, parent_path)
        return label
    else:
        conn = store_or_conn
        row = conn.execute("SELECT to_path FROM domain_merge_map WHERE from_label = ?", (label.lower().strip(),)).fetchone()
        if row:
            return row[0]
        row = conn.execute("SELECT path FROM domains WHERE path = ?", (label,)).fetchone()
        if row:
            return row[0]
        parent_path = "/".join(label.split("/")[:-1]) or None
        conn.execute("INSERT INTO domains (id, path, parent_path, document_count) VALUES (?, ?, ?, 0)",
            (str(uuid.uuid4()), label, parent_path))
        conn.commit()
        return label


def assign_document_domains(store_or_conn, document_id: str, classification: dict) -> list[str]:
    """Assign domains from classification result to a document.

    Accepts either a DataStore or raw sqlite3.Connection.
    """
    all_domains = []

    if hasattr(store_or_conn, 'domains'):
        store = store_or_conn
        primary = classification.get("primary_domain")
        if primary:
            path = normalize_domain_label(store, primary)
            store.domains.assign_document(document_id, path, True, classification.get("confidence", 0.8))
            store.domains.increment_doc_count(path)
            all_domains.append(path)

        for secondary in classification.get("secondary_domains", []):
            path = normalize_domain_label(store, secondary)
            store.domains.assign_document(document_id, path, False, 0.5)
            store.domains.increment_doc_count(path)
            all_domains.append(path)
    else:
        conn = store_or_conn
        primary = classification.get("primary_domain")
        if primary:
            path = normalize_domain_label(conn, primary)
            conn.execute("INSERT OR REPLACE INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, ?, 1, ?)",
                (document_id, path, classification.get("confidence", 0.8)))
            conn.execute("UPDATE domains SET document_count = document_count + 1 WHERE path = ?", (path,))
            all_domains.append(path)

        for secondary in classification.get("secondary_domains", []):
            path = normalize_domain_label(conn, secondary)
            conn.execute("INSERT OR REPLACE INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, ?, 0, ?)",
                (document_id, path, 0.5))
            conn.execute("UPDATE domains SET document_count = document_count + 1 WHERE path = ?", (path,))
            all_domains.append(path)

        conn.commit()

    return all_domains
