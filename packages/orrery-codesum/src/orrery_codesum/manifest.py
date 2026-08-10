"""Manifest parsing for repo -> repo edges within an org.

build_provides_map inspects each repo's manifest files (pyproject.toml,
setup.py, package.json, go.mod) to figure out what package name that repo
declares/provides. repo_import_edges then matches a repo's declared
dependencies against that provides map to find intra-org edges (deps that
are actually other repos in the same org, as opposed to external/third
party packages, which are dropped).
"""
from __future__ import annotations

import re
import tomllib


def _name_from_pyproject(text: str) -> str | None:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        data = None
    if data:
        name = data.get("project", {}).get("name")
        if name:
            return name
        # poetry-style
        name = data.get("tool", {}).get("poetry", {}).get("name")
        if name:
            return name
    # Fallback: tolerant regex parse in case of a non-strict-TOML fixture.
    match = re.search(r'^\s*name\s*=\s*["\']?([\w.\-]+)["\']?', text, re.MULTILINE)
    if match:
        return match.group(1)
    return None


def _name_from_setup_py(text: str) -> str | None:
    match = re.search(r'name\s*=\s*["\']([\w.\-]+)["\']', text)
    if match:
        return match.group(1)
    return None


def _name_from_package_json(text: str) -> str | None:
    match = re.search(r'"name"\s*:\s*"([^"]+)"', text)
    if match:
        return match.group(1)
    return None


def _name_from_go_mod(text: str) -> str | None:
    match = re.search(r'^\s*module\s+(\S+)', text, re.MULTILINE)
    if match:
        return match.group(1)
    return None


_PARSERS = {
    "pyproject.toml": _name_from_pyproject,
    "setup.py": _name_from_setup_py,
    "package.json": _name_from_package_json,
    "go.mod": _name_from_go_mod,
}


def build_provides_map(repos_manifests: dict) -> dict:
    """Map declared package/module name -> repo name.

    repos_manifests: {repo_name: {filename: file_text, ...}, ...}
    """
    provides: dict = {}
    for repo_name, files in repos_manifests.items():
        for filename, text in files.items():
            parser = _PARSERS.get(filename)
            if parser is None:
                continue
            name = parser(text)
            if name:
                provides[name] = repo_name
    return provides


def repo_import_edges(repo: str, declared_deps: list, provides_map: dict) -> list:
    """Return (repo, other_repo) edges for deps that resolve to another org repo.

    External/unknown deps (not in provides_map) are silently dropped, as is
    a dependency that resolves back to the same repo.
    """
    edges = []
    for dep in declared_deps:
        target_repo = provides_map.get(dep)
        if target_repo is None:
            continue
        if target_repo == repo:
            continue
        edges.append((repo, target_repo))
    return edges
