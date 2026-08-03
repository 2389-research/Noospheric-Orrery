"""The four-phase flow: root(provisional) -> leaves -> modules(top-down) ->
root(final). Framing flows down; module evidence is its leaf files."""


def _make_stub():
    calls = []

    def stub(level, *, path="", content="", root="", parent=None, files="", submods=""):
        calls.append({"level": level, "path": path, "root": root,
                      "parent": parent, "files": files, "submods": submods})
        return f"intent:{level}:{path}"

    return stub, calls


def _tree(tmp_path):
    (tmp_path / "README.md").write_text("root readme")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    # a bare src/ wrapper around one package -> should collapse
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "a.py").write_text("import os\n")
    (tmp_path / "src" / "pkg" / "b.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test(): pass\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.py").write_text("x=1")


def test_repo_first_and_levels_present(tmp_path):
    _tree(tmp_path)
    from orrery_codesum.traverse import summarize_repo
    stub, _ = _make_stub()
    arts = summarize_repo(str(tmp_path), stub, repo_name="demo")
    assert arts[0]["level"] == "repo"
    assert arts[0]["path"] == "."
    assert arts[0]["parent_path"] is None
    levels = {a["level"] for a in arts}
    assert {"repo", "module", "file"} <= levels


def test_root_computed_twice(tmp_path):
    _tree(tmp_path)
    from orrery_codesum.traverse import summarize_repo
    stub, calls = _make_stub()
    summarize_repo(str(tmp_path), stub, repo_name="demo")
    called_levels = [c["level"] for c in calls]
    assert called_levels[0] == "root_provisional"    # orientation first
    assert called_levels[-1] == "root_final"         # refinement last
    # the final repo artifact carries the root_final intent
    arts = summarize_repo(str(tmp_path), stub, repo_name="demo")
    assert arts[0]["intent"] == "intent:root_final:."


def test_wrapper_collapse_and_parent_paths(tmp_path):
    _tree(tmp_path)
    from orrery_codesum.traverse import summarize_repo
    stub, _ = _make_stub()
    arts = summarize_repo(str(tmp_path), stub, repo_name="demo")
    module_paths = {a["path"] for a in arts if a["level"] == "module"}
    # bare src/ wrapper collapses; its package attaches to the repo root
    assert "src" not in module_paths
    assert "src/pkg" in module_paths
    assert "tests" in module_paths
    src_pkg = next(a for a in arts if a["path"] == "src/pkg")
    assert src_pkg["parent_path"] == "."             # reparented to root by collapse
    a_py = next(a for a in arts if a["path"] == "src/pkg/a.py")
    assert a_py["level"] == "file"
    assert a_py["parent_path"] == "src/pkg"          # file's parent is its module


def test_module_evidence_is_its_leaf_files(tmp_path):
    _tree(tmp_path)
    from orrery_codesum.traverse import summarize_repo
    stub, calls = _make_stub()
    summarize_repo(str(tmp_path), stub, repo_name="demo")
    module_call = next(c for c in calls if c["level"] == "module" and c["path"] == "src/pkg")
    # module summary is fed the leaf summaries of a.py and b.py, plus root framing
    assert "intent:leaf:src/pkg/a.py" in module_call["files"]
    assert "intent:leaf:src/pkg/b.py" in module_call["files"]
    assert module_call["root"] == "intent:root_provisional:."


def test_skipped_dirs_excluded(tmp_path):
    _tree(tmp_path)
    from orrery_codesum.traverse import summarize_repo
    stub, _ = _make_stub()
    arts = summarize_repo(str(tmp_path), stub, repo_name="demo")
    assert all("node_modules" not in a["path"] for a in arts)


def test_symlinks_are_not_read_or_traversed(tmp_path):
    """An untrusted repo must not be able to leak host data via symlinks."""
    from orrery_codesum.traverse import _all_files, _read_text_safe

    secret = tmp_path / "outside_secret.env"
    secret.write_text("SECRET=leaked\n")
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "real.py").write_text("x = 1\n")
    # symlinked file pointing at host data, and a symlinked directory
    (repo / "pkg" / "creds.py").symlink_to(secret)
    (repo / "evil_dir").symlink_to(tmp_path)

    files = list(_all_files(str(repo)))
    assert any(f.endswith("real.py") for f in files)
    assert all(not f.endswith("creds.py") for f in files)      # symlinked file skipped
    assert all("evil_dir" not in f for f in files)             # symlinked dir not traversed
    assert _read_text_safe(str(repo / "pkg" / "creds.py")) == ""  # refuses to read symlink


def test_root_content_respects_aggregate_budget(tmp_path):
    from orrery_codesum.traverse import _build_root_content, MAX_ROOT_CONTENT_CHARS

    (tmp_path / "README.md").write_text("A" * (MAX_ROOT_CONTENT_CHARS * 2))
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    content = _build_root_content(str(tmp_path))
    assert len(content) <= MAX_ROOT_CONTENT_CHARS + len("\n... [truncated]")


def test_fileless_structural_dir_emits_no_ungrounded_module(tmp_path):
    """A dir with no files of its own (only sub-dirs) has no leaf evidence, so it
    must not emit a module node; its sub-modules attach to its parent."""
    from orrery_codesum.traverse import summarize_repo, REPO_PATH

    (tmp_path / "README.md").write_text("readme")
    # `group/` has no files, only two sub-packages that DO have files.
    (tmp_path / "group" / "x").mkdir(parents=True)
    (tmp_path / "group" / "x" / "x.py").write_text("x = 1\n")
    (tmp_path / "group" / "y").mkdir(parents=True)
    (tmp_path / "group" / "y" / "y.py").write_text("y = 2\n")

    stub, _ = _make_stub()
    arts = summarize_repo(str(tmp_path), stub, repo_name="demo")
    modules = {a["path"]: a for a in arts if a["level"] == "module"}
    assert "group" not in modules                     # fileless dir omitted
    assert "group/x" in modules and "group/y" in modules
    # its sub-modules re-parent to the repo root
    assert modules["group/x"]["parent_path"] == REPO_PATH
    assert modules["group/y"]["parent_path"] == REPO_PATH
