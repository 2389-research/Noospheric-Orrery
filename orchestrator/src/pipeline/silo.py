# ABOUTME: Resolve documents.silo_id at ingest and the SQL fragment that scopes
# ABOUTME: normalization to a silo. MIRROR of worker/src/silo.py: everything below
# ABOUTME: this header must stay byte-identical (enforced by
# ABOUTME: orchestrator/tests/test_schema_mirror.py), like classifier.py.

def resolve_silo_id(source_id, collection_id):
    """Precedence: source_id > collection_id > None (spec §5)."""
    return source_id or collection_id or None


# SQL fragment: <entity_col> has at least one source in the silo bound to a POSITIONAL ? (NULL-safe).
# Positional `?` everywhere (sqlite raises if one statement mixes named + numbered params).
def silo_match(entity_col: str) -> str:
    return (f"EXISTS (SELECT 1 FROM entity_sources es JOIN documents d ON d.id = es.document_id "
            f"WHERE es.entity_id = {entity_col} AND d.silo_id IS ?)")
