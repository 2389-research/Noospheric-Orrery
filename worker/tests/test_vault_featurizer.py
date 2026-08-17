# ABOUTME: enumerate_vault yields one (path, title, content, emits) per non-empty note.

from src.featurizers.vault import enumerate_vault


def test_yields_only_nonempty_markdown(tmp_path):
    (tmp_path / "a.md").write_text("alpha content")
    (tmp_path / "b.md").write_text("beta content")
    (tmp_path / "empty.md").write_text("   \n\t")
    (tmp_path / "note.txt").write_text("txt content")

    out = list(enumerate_vault(str(tmp_path), {}))
    assert {t for (_, t, _, _) in out} == {"a", "b"}
    assert all(emits is True for (_, _, _, emits) in out)
    assert str(tmp_path / "note.txt") not in {p for (p, _, _, _) in out}
    assert str(tmp_path / "empty.md") not in {p for (p, _, _, _) in out}


def test_ext_override(tmp_path):
    (tmp_path / "a.md").write_text("md")
    (tmp_path / "n.txt").write_text("txt")
    out = list(enumerate_vault(str(tmp_path), {"ext": ["txt"]}))
    assert {t for (_, t, _, _) in out} == {"n"}


def test_recurses_into_subdirs(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.md").write_text("deep content")
    out = list(enumerate_vault(str(tmp_path), {}))
    assert {t for (_, t, _, _) in out} == {"deep"}


def test_missing_directory_yields_nothing(tmp_path):
    assert list(enumerate_vault(str(tmp_path / "does-not-exist"), {})) == []
