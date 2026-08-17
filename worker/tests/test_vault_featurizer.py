# ABOUTME: enumerate_vault yields one SourceDoc per non-empty note (walk/parse/clean/hint).

from pathlib import Path

from src.featurizers.vault import enumerate_vault


def test_yields_only_nonempty_markdown(tmp_path):
    (tmp_path / "a.md").write_text("alpha content")
    (tmp_path / "b.md").write_text("beta content")
    (tmp_path / "empty.md").write_text("   \n\t")
    (tmp_path / "note.txt").write_text("txt content")

    out = list(enumerate_vault(str(tmp_path), {}))
    assert {d.title for d in out} == {"a", "b"}
    assert all(d.emits_cooccurrence is True for d in out)
    assert str(tmp_path / "note.txt") not in {d.source_path for d in out}
    assert str(tmp_path / "empty.md") not in {d.source_path for d in out}


def test_ext_override(tmp_path):
    (tmp_path / "a.md").write_text("md")
    (tmp_path / "n.txt").write_text("txt")
    out = list(enumerate_vault(str(tmp_path), {"ext": ["txt"]}))
    assert {d.title for d in out} == {"n"}


def test_recurses_into_subdirs(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.md").write_text("deep content")
    out = list(enumerate_vault(str(tmp_path), {}))
    assert {d.title for d in out} == {"deep"}


def test_missing_directory_yields_nothing(tmp_path):
    assert list(enumerate_vault(str(tmp_path / "does-not-exist"), {})) == []


def test_folder_becomes_domain_hint_when_enabled(tmp_path):
    (tmp_path / "Projects" / "Orrery").mkdir(parents=True)
    (tmp_path / "Projects" / "Orrery" / "note.md").write_text("body text", encoding="utf-8")
    docs = list(enumerate_vault(str(tmp_path), {"folder_domains": True}))
    assert docs[0].domain_hint == "projects/orrery"


def test_no_domain_hint_by_default(tmp_path):
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "note.md").write_text("body", encoding="utf-8")
    docs = list(enumerate_vault(str(tmp_path), {}))
    assert docs[0].domain_hint is None


def _make_vault(root: Path):
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (root / ".trash").mkdir()
    (root / ".trash" / "deleted.md").write_text("I was deleted", encoding="utf-8")
    (root / "note.md").write_text(
        "---\ntitle: Real Note\ntags: [a]\n---\n"
        "Body mentions [[Other Note]] and %%a secret%% here.\n", encoding="utf-8")
    (root / "attach.png").write_bytes(b"\x89PNG\r\n")


def test_vault_import_acceptance(tmp_path):
    _make_vault(tmp_path)
    docs = list(enumerate_vault(str(tmp_path), {}))

    paths = [Path(d.source_path).name for d in docs]
    assert paths == ["note.md"]                       # no .obsidian/.trash/.png junk
    doc = docs[0]
    assert doc.title == "Real Note"                   # frontmatter title wins over stem
    assert "tags:" not in doc.content                 # frontmatter stripped
    assert "%%" not in doc.content                    # comment stripped
    assert "[[" not in doc.content and "Other Note" in doc.content  # wikilink cleaned
    assert doc.metadata["tags"] == ["a"]              # provenance carried
