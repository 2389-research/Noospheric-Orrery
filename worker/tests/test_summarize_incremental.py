# ABOUTME: summarize_repo_incremental — re-summarize only changed nodes, reuse the cache.
# ABOUTME: Asserts model-call counts for changed / unchanged / threshold-gated / forced.

from orrery_codesum import summarize_repo_incremental


def _fn(calls):
    def summarize_fn(level, *, path=None, content=None, root=None, parent=None, files=None, submods=None):
        calls.append((level, path))
        return f"{level}:{path}"
    return summarize_fn


def _mkrepo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "mod").mkdir(parents=True)
    (repo / "mod" / "a.py").write_text("def a(): pass\n")
    (repo / "mod" / "b.py").write_text("def b(): pass\n")
    return str(repo)


def _cache(artifacts):
    return {a["path"]: a["intent"] for a in artifacts}


def test_full_pass_summarizes_everything(tmp_path):
    root = _mkrepo(tmp_path)
    calls = []
    arts = summarize_repo_incremental(root, _fn(calls), "repo", cache={}, changed=None)
    levels = {(lvl, p) for lvl, p in calls}
    assert ("leaf", "mod/a.py") in levels and ("leaf", "mod/b.py") in levels
    assert ("module", "mod") in levels
    assert any(lvl == "root_final" for lvl, _ in calls)
    assert {a["path"] for a in arts} == {".", "mod", "mod/a.py", "mod/b.py"}


def test_only_changed_leaf_and_its_ancestors_resummarize(tmp_path):
    root = _mkrepo(tmp_path)
    cache = _cache(summarize_repo_incremental(root, _fn([]), "repo", cache={}, changed=None))

    calls = []
    summarize_repo_incremental(root, _fn(calls), "repo", cache=cache, changed={"mod/a.py"})
    leaves = {p for lvl, p in calls if lvl == "leaf"}
    assert leaves == {"mod/a.py"}                          # b.py reused, not re-summarized
    assert ("module", "mod") in calls                      # module has a changed file
    assert any(lvl == "root_final" for lvl, _ in calls)    # top-level module changed


def test_module_threshold_gates_the_module_summary(tmp_path):
    root = _mkrepo(tmp_path)
    cache = _cache(summarize_repo_incremental(root, _fn([]), "repo", cache={}, changed=None))

    calls = []
    # 1 of 2 files changed = 0.5 < 0.6 -> leaf re-summarizes, module/root do NOT.
    summarize_repo_incremental(root, _fn(calls), "repo", cache=cache,
                               changed={"mod/a.py"}, module_change_ratio=0.6)
    assert ("leaf", "mod/a.py") in calls
    assert ("module", "mod") not in calls
    assert not any(lvl == "root_final" for lvl, _ in calls)


def test_nothing_changed_calls_no_model(tmp_path):
    root = _mkrepo(tmp_path)
    cache = _cache(summarize_repo_incremental(root, _fn([]), "repo", cache={}, changed=None))
    calls = []
    summarize_repo_incremental(root, _fn(calls), "repo", cache=cache, changed=set())
    assert calls == []                                     # zero model calls


def test_force_modules_resummarizes_even_with_no_content_change(tmp_path):
    root = _mkrepo(tmp_path)
    cache = _cache(summarize_repo_incremental(root, _fn([]), "repo", cache={}, changed=None))
    calls = []
    # a file was deleted from mod -> force its module (and thus root) to refresh
    summarize_repo_incremental(root, _fn(calls), "repo", cache=cache,
                               changed=set(), force_modules={"mod"})
    assert ("module", "mod") in calls
    assert any(lvl == "root_final" for lvl, _ in calls)
    assert not any(lvl == "leaf" for lvl, _ in calls)      # no leaf touched
