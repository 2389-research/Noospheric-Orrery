import uuid

from ..repositories.interfaces import _UNSET


def normalize_entity(store_or_conn, name: str, entity_type: str, silo=_UNSET) -> str:
    """Normalize an entity name: check merge map, find existing, or create new.

    Accepts either a DataStore or raw sqlite3.Connection for backward compat.

    `silo` scopes the dedup lookup to a source silo. Omit it (default sentinel)
    for unscoped, back-compat behavior; pass `silo=None` explicitly to scope to
    the null-silo pool (loose uploads), or a real silo id to scope to that silo.
    """
    clean_name = name.lower().strip()

    # Duck-type: if it has .normalization, it's a store
    if hasattr(store_or_conn, 'normalization'):
        store = store_or_conn
        # Check merge map
        merged_to = store.normalization.get_merge_map_entry(clean_name, silo=silo)
        if merged_to:
            return merged_to
        # Check existing entity — include invalidated nodes so a re-mention
        # re-attaches to the (still-invalidated) node instead of duplicating it.
        existing = store.entities.get_by_name(clean_name, entity_type, include_invalid=True, silo=silo)
        if existing:
            return existing.id
        # Create new
        entity_id = str(uuid.uuid4())
        store.entities.create(entity_id, clean_name, entity_type)
        return entity_id
    else:
        # Legacy: raw connection.
        # ⚠️ DEPRECATED / silo-UNAWARE: this branch ignores `silo` entirely — no
        # per-silo scoping of merge_map or the canonical lookup, and no cross-silo
        # proposal. It will auto-merge same-name entities ACROSS silos, defeating
        # #50. No production caller reaches it (every one passes a store, which
        # hits the silo-aware branch above); it survives only for legacy/raw-conn
        # callers and tests. Do not route new code through it — pass a store.
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
