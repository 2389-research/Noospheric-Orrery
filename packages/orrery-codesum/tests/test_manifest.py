def test_provides_map_and_repo_edges(tmp_path):
    from orrery_codesum.manifest import build_provides_map, repo_import_edges
    provides = build_provides_map({"A": {"pyproject.toml": '[project]\nname="alpha"\n'}})
    assert provides["alpha"] == "A"
    edges = repo_import_edges("B", ["alpha", "requests"], provides)
    assert ("B", "A") in edges                 # intra-org hit
    assert all("requests" not in e for e in edges)   # external miss dropped


def test_a_package_name_claimed_by_two_repos_yields_no_edge():
    """Last-writer-wins made the edge depend on iteration order.

    Two repos declaring the same package name (a fork, a vendored copy, a monorepo
    re-declaration) resolved to whichever was processed last, so `uses` pointed at an
    arbitrary repo while looking exactly like a real edge. The graph is used to decide
    where to look, so a wrong edge costs more than a missing one.
    """
    from orrery_codesum.manifest import build_provides_map, repo_import_edges

    manifests = {
        "repo-a": {"pyproject.toml": '[project]\nname = "shared"\n'},
        "repo-b": {"pyproject.toml": '[project]\nname = "shared"\n'},
        "repo-c": {"pyproject.toml": '[project]\nname = "unique"\n'},
    }
    provides = build_provides_map(manifests)

    assert repo_import_edges("consumer", ["shared"], provides) == []
    # An unambiguous name still resolves — the guard is not a blanket disable.
    assert repo_import_edges("consumer", ["unique"], provides) == [("consumer", "repo-c")]


def test_one_repo_declaring_the_same_name_twice_is_not_ambiguous():
    """Only a genuine cross-repo clash is ambiguous.

    A repo whose setup.py and pyproject.toml agree on the name must still resolve, or
    the guard would silently disable edges for ordinary projects.
    """
    from orrery_codesum.manifest import build_provides_map, repo_import_edges

    provides = build_provides_map({
        "repo-a": {"pyproject.toml": '[project]\nname = "thing"\n',
                   "setup.py": 'setup(name="thing")\n'},
    })
    assert repo_import_edges("consumer", ["thing"], provides) == [("consumer", "repo-a")]
