import uuid


def normalize_entity(store_or_conn, name: str, entity_type: str) -> str:
    """Normalize an entity name: check merge map, find existing, or create new.

    Accepts either a DataStore or raw sqlite3.Connection for backward compat.
    """
    clean_name = name.lower().strip()

    # Duck-type: if it has .normalization, it's a store
    if hasattr(store_or_conn, 'normalization'):
        store = store_or_conn
        # Check merge map
        merged_to = store.normalization.get_merge_map_entry(clean_name)
        if merged_to:
            return merged_to
        # Check existing entity
        existing = store.entities.get_by_name(clean_name, entity_type)
        if existing:
            return existing.id
        # Create new
        entity_id = str(uuid.uuid4())
        store.entities.create(entity_id, clean_name, entity_type)
        return entity_id
    else:
        # Legacy: raw connection
        conn = store_or_conn
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
