# ABOUTME: Task 4 — normalize_entity (loose-upload inline dedup) must be silo-aware
# ABOUTME: via the store's get_by_name / get_merge_map_entry, not just raw SQL.

import hashlib

from src.pipeline.normalizer import normalize_entity


def _make_siloed_entity(store, silo_id: str, name: str = "mercury", entity_type: str = "Concept") -> str:
    """Create a document in `silo_id`, an entity, and an entity_sources row
    attaching the entity to that document — mirrors what a siloed ingest does."""
    doc_id = f"doc-{silo_id}"
    content = f"content for {silo_id}"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    store.documents.create(doc_id, f"title-{silo_id}", content, content_hash, None, silo_id=silo_id)
    entity_id = store.entities.create(f"entity-{silo_id}", name, entity_type)
    store.entity_sources.create(entity_id=entity_id, document_id=doc_id, chunk_id=None,
                                 extraction_pass="general", spec_version=0)
    return entity_id


def test_loose_upload_does_not_fuse_onto_siloed_entity(test_store):
    """A null-silo (loose upload) mention of 'mercury' must NOT fuse onto an
    entity that only exists within silo 'v1' — it must create a new entity."""
    siloed_id = _make_siloed_entity(test_store, "v1")

    loose_id = normalize_entity(test_store, "mercury", "Concept", silo=None)

    assert loose_id != siloed_id
    # And it's a real, newly-created entity.
    entity = test_store.entities.get(loose_id)
    assert entity is not None
    assert entity.canonical_name == "mercury"


def test_two_null_silo_mentions_still_fuse(test_store):
    """Regression: two loose (null-silo) mentions of the same name must still
    resolve to the SAME entity — silo-scoping must not break the null pool.

    Mirrors the real ingest flow: normalize_entity() only resolves/creates the
    entity — the caller (_ingest_document) attaches entity_sources right after,
    per mention, before the next document is normalized."""
    content_hash1 = hashlib.sha256(b"loose doc 1").hexdigest()
    test_store.documents.create("loose-doc-1", "loose 1", "loose doc 1", content_hash1, None, silo_id=None)
    first_id = normalize_entity(test_store, "mercury", "Concept", silo=None)
    test_store.entity_sources.create(entity_id=first_id, document_id="loose-doc-1", chunk_id=None,
                                      extraction_pass="general", spec_version=0)

    content_hash2 = hashlib.sha256(b"loose doc 2").hexdigest()
    test_store.documents.create("loose-doc-2", "loose 2", "loose doc 2", content_hash2, None, silo_id=None)
    second_id = normalize_entity(test_store, "mercury", "Concept", silo=None)

    assert first_id == second_id


def test_unscoped_call_keeps_back_compat_behavior(test_store):
    """Callers that omit `silo` entirely (today's other call sites) must keep
    matching across silos — the sentinel default preserves old behavior."""
    siloed_id = _make_siloed_entity(test_store, "v1", name="venus")

    # No silo kwarg passed at all.
    matched_id = normalize_entity(test_store, "venus", "Concept")

    assert matched_id == siloed_id


def test_loose_image_upload_does_not_fuse_onto_siloed_entity(test_store):
    """Same leak as the loose-text-upload case, but for _ingest_image's call
    shape: a loose (null-silo) image upload extracting 'mercury'/Concept must
    NOT fuse onto an entity that only exists within silo 'v1'. _ingest_image
    creates its document with silo_id defaulting to None (see
    routes/ingest.py), so this exercises normalize_entity(..., silo=None)
    exactly as that route now calls it."""
    siloed_id = _make_siloed_entity(test_store, "v1")

    loose_image_id = normalize_entity(test_store, "mercury", "Concept", silo=None)

    assert loose_image_id != siloed_id
    entity = test_store.entities.get(loose_image_id)
    assert entity is not None
    assert entity.canonical_name == "mercury"


def test_ingest_image_call_site_passes_silo_none():
    """Guard against the exact regression the reviewer caught: _ingest_image's
    normalize_entity() call must pass silo=None (loose image uploads are the
    null-silo pool), not run unscoped."""
    import inspect
    from src.routes import ingest

    source = inspect.getsource(ingest._ingest_image)
    assert 'normalize_entity(store, entity["name"], entity["type"], silo=None)' in source
