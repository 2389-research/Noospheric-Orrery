from fastapi import APIRouter, HTTPException
from ..dependencies import get_auth_store, AuthStore
from ..repositories.factory import get_store

router = APIRouter()

@router.get("/entities")
def list_entities(
    limit: int = 50,
    offset: int = 0,
    type: str | None = None,
    domain: str | None = None,
    job_id: str | None = None,
):
    store = get_store()
    entities = store.entities.list(
        limit=limit, offset=offset,
        type_filter=type, domain_filter=domain, job_id=job_id,
    )
    store.close()
    return [{"id": e.id, "canonical_name": e.canonical_name, "type": e.type,
             "source_count": e.source_count} for e in entities]


@router.get("/entities/{entity_id}/cooccurrences")
def get_cooccurrences(entity_id: str, limit: int = 10):
    store = get_store()
    coentities = store.relationships.get_cooccurrences(entity_id, limit=limit)
    store.close()
    return [{"id": c.id, "canonical_name": c.canonical_name, "type": c.type,
             "weight": c.weight} for c in coentities]


@router.get("/entities/{entity_id}/star-graph")
def get_star_graph(entity_id: str, co_limit: int = 30):
    store = get_store()
    result = store.relationships.get_star_graph(entity_id, co_limit=co_limit)
    if not result:
        store.close()
        raise HTTPException(status_code=404, detail="Entity not found")
    store.close()
    return result


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str):
    store = get_store()
    entity = store.entities.get(entity_id)
    if not entity:
        store.close()
        raise HTTPException(status_code=404, detail="Entity not found")
    sources = store.entity_sources.get_for_entity(entity_id)
    merge_history = store.normalization.get_merge_history(entity_id)
    store.close()
    return {
        "id": entity.id, "canonical_name": entity.canonical_name, "type": entity.type,
        "created_at": entity.created_at,
        "sources": [{"document_id": s.document_id, "chunk_id": s.chunk_id,
                      "extraction_pass": s.extraction_pass, "spec_version": s.spec_version,
                      "job_id": s.job_id} for s in sources],
        "merge_history": merge_history,
    }
