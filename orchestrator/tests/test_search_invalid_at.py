"""Search must hide soft-deleted entities, like every other surface.

An entity removed through the corrections flow (`entities.invalid_at`) was still
reachable through search. Every other read already filtered it — graph_ops and the
repositories both do — so search was the single surface where a "deleted" node came
back, which is worse than never having supported deletion: the graph says one thing
and the search box says another.

Three separate holes, because there are three ways an entity reaches a result:

1. the FAISS index build,
2. the lexical (exact / substring) lookup, which bypasses the vector index entirely,
3. per-hit hydration.

(3) matters independently of (1): the index is built periodically, so an entity
invalidated SINCE the last build is still a live hit no matter how clean the build
filter is. Closing only the build would look correct in a fresh test and fail in
production.
"""

import numpy as np

from src.pipeline.search import retrieval


def _seed(store):
    """Seed WITH stored embeddings, which is also the production case.

    `build_indexes` only reaches for the SentenceTransformer when a row is missing one,
    so pre-storing them keeps this test off the model-download path and fast. The
    vectors are arbitrary — nothing here asserts on semantic distance, only membership.
    """
    c = store.conn
    c.execute("INSERT INTO documents (id, title) VALUES ('d0', 'doc')")
    for i, name in enumerate(["alpha widget", "beta widget", "gamma widget"]):
        vec = np.zeros(384, dtype=np.float32)
        vec[i] = 1.0
        c.execute("INSERT INTO entities (id, canonical_name, type, embedding) VALUES (?, ?, ?, ?)",
                  (f"e{i}", name, "Concept", vec.tobytes()))
        c.execute("INSERT INTO entity_sources (entity_id, document_id) VALUES (?, 'd0')", (f"e{i}",))
    c.commit()


def _invalidate(store, eid):
    store.conn.execute("UPDATE entities SET invalid_at = datetime('now') WHERE id = ?", (eid,))
    store.conn.commit()


def test_invalidated_entity_never_enters_the_index(test_store, monkeypatch):
    _seed(test_store)
    _invalidate(test_store, "e1")

    # Pin the laziness as well as the filter. Every embedding is stored, so there is
    # nothing to encode and touching the model at all is the bug — on a cold host it
    # DOWNLOADS all-MiniLM-L6-v2, which is why CI hung when build_indexes loaded it
    # unconditionally.
    def _no_model():
        raise AssertionError("build_indexes loaded the embedding model with nothing to encode")
    monkeypatch.setattr(retrieval, "_get_model", _no_model)

    retrieval.build_indexes(test_store.conn)
    assert "e1" not in (retrieval._entity_ids or [])
    assert {"e0", "e2"} <= set(retrieval._entity_ids or [])


def test_lexical_lookup_hides_invalidated_entities(test_store):
    """Exact and substring matching bypass the vector index, so they need the filter
    in their own right — a clean index does not protect them."""
    _seed(test_store)
    _invalidate(test_store, "e1")

    hits = retrieval.search_entities_exact(test_store.conn, "beta widget")
    assert "e1" not in {h.entity_id for h in hits}

    partial = retrieval.search_entities_exact(test_store.conn, "widget")
    ids = {h.entity_id for h in partial}
    assert "e1" not in ids
    assert ids & {"e0", "e2"}, "active entities should still match"


def test_hydration_drops_entities_invalidated_since_the_last_index_build(test_store):
    """The hole the build-time filter cannot close.

    The index is built periodically, so an entity invalidated AFTER the last build is
    still a live hit. Enrichment must DROP it — merely skipping the name/type fill
    leaves it in the list with blank metadata, and fusion then returns a soft-deleted
    entity anyway.
    """
    from src.pipeline.search.models import ScoredEntity, SubQueryResults
    from src.pipeline.search.pipeline import _enrich_results

    _seed(test_store)
    hits = [ScoredEntity(entity_id=f"e{i}", name="", entity_type="", score=1.0 - i / 10,
                         rank=i + 1, source="semantic") for i in range(3)]
    results = SubQueryResults(query="widget", semantic_entities=hits)

    # Invalidate AFTER the hits exist — i.e. after the index that produced them.
    _invalidate(test_store, "e1")
    _enrich_results(test_store.conn, results)

    surviving = [e.entity_id for e in results.semantic_entities]
    assert surviving == ["e0", "e2"], "the invalidated hit is dropped, order otherwise kept"
    assert all(e.name and e.entity_type for e in results.semantic_entities), \
        "survivors are enriched, not merely retained"


def test_entity_boost_does_not_reach_through_an_invalidated_entity(test_store):
    """The boost joins chunks via shared entities, so an unfiltered join lets a
    soft-deleted entity keep pulling chunks into the results."""
    from src.pipeline.search.config import SearchConfig
    from src.pipeline.search.entity_boost import boost_chunks_via_entities
    from src.pipeline.search.models import ScoredEntity, SubQueryResults

    _seed(test_store)
    c = test_store.conn
    c.execute("INSERT INTO chunks (id, document_id, chunk_index, text) VALUES ('c0', 'd0', 0, 'x')")
    c.execute("UPDATE entity_sources SET chunk_id = 'c0'")
    c.commit()
    _invalidate(test_store, "e1")

    def boost_for(entity_id):
        hit = ScoredEntity(entity_id=entity_id, name="w", entity_type="Concept",
                           score=1.0, rank=1, source="semantic", source_count=1)
        out = boost_chunks_via_entities(
            c, SubQueryResults(query="widget", semantic_entities=[hit]),
            SearchConfig(), total_docs=1)
        return [ch.chunk_id for ch in out.boosted_chunks]

    assert boost_for("e1") == [], "an invalidated entity must not surface chunks"
    # ...and the mechanism still works, so the empty result above is the filter
    # rather than a broken query.
    assert boost_for("e0") == ["c0"]


def test_the_search_package_is_not_shadowed_by_a_module(test_store):
    """`pipeline/search.py` sat beside `pipeline/search/` and lost to it.

    Python prefers the package, so the module was unreachable — but it looked like the
    implementation, and a fix aimed at search could land there and change nothing. It
    was deleted; this keeps it deleted.
    """
    from pathlib import Path

    import src.pipeline as pipeline_pkg

    pipeline_dir = Path(pipeline_pkg.__file__).parent
    assert not (pipeline_dir / "search.py").exists(), (
        "pipeline/search.py is shadowed by pipeline/search/ and can never run — "
        "edits to it are silently inert")
    assert (pipeline_dir / "search" / "retrieval.py").exists()


def test_a_correction_marks_the_search_index_stale(test_store):
    """Filtering the results is necessary but not sufficient.

    The FAISS index is built once per process. Dropping invalidated hits at read time
    stops a deleted entity from APPEARING, but the stale vector still occupied a top-k
    slot on the way through — so an active entity ranked just below it silently never
    surfaces. The correction has to invalidate the index too.
    """
    from src.pipeline import graph_repair
    from src.pipeline.search import pipeline as search_pipeline

    _seed(test_store)
    search_pipeline._indexes_ready = True          # simulate an index built earlier

    graph_repair.apply_invalidation(test_store.conn, "e1", reason="test")

    assert search_pipeline._indexes_ready is False, (
        "a soft delete must force a rebuild; otherwise the removed entity keeps "
        "consuming a result slot that an active entity should have had")


def test_rolling_a_correction_back_also_marks_the_index_stale(test_store):
    """The inverse case: an index built WHILE the entity was invalid does not contain
    it, so restoring the entity has to rebuild too or it stays invisible."""
    from src.pipeline import graph_repair
    from src.pipeline.search import pipeline as search_pipeline

    _seed(test_store)
    graph_repair.apply_invalidation(test_store.conn, "e1", reason="test")
    search_pipeline._indexes_ready = True

    graph_repair.rollback_invalidation(test_store.conn, "e1")

    assert search_pipeline._indexes_ready is False
