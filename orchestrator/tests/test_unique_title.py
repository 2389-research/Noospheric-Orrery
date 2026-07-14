"""#24 pt2: same-filename uploads must stay distinguishable.

Duplicate *content* is already deduped by content_hash. Duplicate *filenames*
with different content should get a distinguishable display title
(README.md → README.md (2)) instead of two indistinguishable rows.
"""

from src.routes.ingest import _unique_title


def test_passthrough_when_title_free(test_store):
    assert _unique_title(test_store, "README.md") == "README.md"


def test_appends_counter_on_collision(test_store):
    test_store.documents.create("d1", "README.md", "content-a", "hash-a")
    assert _unique_title(test_store, "README.md") == "README.md (2)"


def test_increments_past_existing_suffixes(test_store):
    test_store.documents.create("d1", "README.md", "a", "ha")
    test_store.documents.create("d2", "README.md (2)", "b", "hb")
    assert _unique_title(test_store, "README.md") == "README.md (3)"


def test_handles_titles_without_extension(test_store):
    test_store.documents.create("d1", "notes", "a", "ha")
    assert _unique_title(test_store, "notes") == "notes (2)"
