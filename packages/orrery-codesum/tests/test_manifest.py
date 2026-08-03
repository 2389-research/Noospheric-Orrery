def test_provides_map_and_repo_edges(tmp_path):
    from orrery_codesum.manifest import build_provides_map, repo_import_edges
    provides = build_provides_map({"A": {"pyproject.toml": '[project]\nname="alpha"\n'}})
    assert provides["alpha"] == "A"
    edges = repo_import_edges("B", ["alpha", "requests"], provides)
    assert ("B", "A") in edges                 # intra-org hit
    assert all("requests" not in e for e in edges)   # external miss dropped
