import sqlite3
import uuid

def normalize_entity(conn: sqlite3.Connection, name: str, entity_type: str) -> str:
    clean_name = name.lower().strip()
    row = conn.execute("SELECT to_entity_id FROM merge_map WHERE from_name = ?", (clean_name,)).fetchone()
    if row:
        return row[0]
    row = conn.execute("SELECT id FROM entities WHERE canonical_name = ? AND type = ?", (clean_name, entity_type)).fetchone()
    if row:
        return row[0]
    entity_id = str(uuid.uuid4())
    conn.execute("INSERT INTO entities (id, canonical_name, type) VALUES (?, ?, ?)", (entity_id, clean_name, entity_type))
    conn.commit()
    return entity_id
