import sqlite3
import uuid

def normalize_domain_label(conn: sqlite3.Connection, label: str) -> str:
    """Check merge map, then insert as new domain if not found.
    Full embedding-based normalization will be added later.
    """
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

def assign_document_domains(conn: sqlite3.Connection, document_id: str, classification: dict) -> list[str]:
    all_domains = []
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

    for new_domain in classification.get("new_domains", []):
        normalize_domain_label(conn, new_domain)

    conn.commit()
    return all_domains
