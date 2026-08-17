from src.featurizers.base import SourceDoc


def test_coerce_passthrough():
    d = SourceDoc(source_path="/v/a.md", title="a", content="body")
    assert SourceDoc.coerce(d) is d
    assert d.emits_cooccurrence is True
    assert d.metadata is None and d.domain_hint is None


def test_coerce_legacy_4_tuple():
    d = SourceDoc.coerce(("/v/a.md", "a", "body", False))
    assert (d.source_path, d.title, d.content, d.emits_cooccurrence) == ("/v/a.md", "a", "body", False)


def test_coerce_legacy_3_tuple_defaults_emit_true():
    d = SourceDoc.coerce(("/v/a.md", "a", "body"))
    assert d.emits_cooccurrence is True
