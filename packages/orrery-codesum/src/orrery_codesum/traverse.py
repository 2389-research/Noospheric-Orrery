"""Phase 1 ingest traversal: recursive intent summarization.

Flow (see docs/superpowers/specs/2026-07-16-summarization-flow-design.md):

    1. ROOT (provisional)  — orientation from README/deps/entry-points/tree.
    2. LEAVES              — every file, framed by the provisional root.
    3. MODULES (top-down)  — parent before child; framed by root + parent
                             module, evidence = summaries of the files in it.
    4. ROOT (final)        — re-derived from the top-level module summaries;
                             this is the stored repo artifact.

Framing flows down; a module's evidence is its LEAF files (never child-module
summaries), so there is no cycle. Order is always root -> leaves -> modules ->
root; documentation presence only changes the provisional root's inputs and how
much work step 4 does.

Returned artifacts are flat dicts (contract unchanged, so persistence in
worker/ingest_repo.py is untouched):
    {"repo": <name>, "path": <relpath>, "level": "repo"|"module"|"file",
     "parent_path": <str or None>, "intent": <summary str>}
"""
from __future__ import annotations

import os

from .fileselect import should_skip_dir, should_skip_file

REPO_PATH = "."  # relpath sentinel identifying the repo artifact itself

MAX_FILE_CHARS = 16000        # per-file leaf budget (was 4000 in the old flow)
MAX_ENTRYPOINT_CHARS = 3000   # per entry-point file in the root orientation
MAX_ENTRYPOINTS = 2
# Aggregate cap on the provisional-root orientation content. Without it, a big
# README plus several 16k manifests plus entry-points plus the tree can exceed
# the model's context window. README/manifests/entry-points are assembled before
# the tree, so trimming the tail drops the (least essential) structure listing first.
MAX_ROOT_CONTENT_CHARS = 24000
# Root-orientation tree listing bounds. The recursive listing is only useful for
# orientation near the top; without a bound a large repo (many crates/site/docs)
# produces a path listing that alone blows the model's context window. Keep the
# README/manifest/entry-points intact and trim only the long tail of paths.
MAX_TREE_DEPTH = 3
MAX_TREE_ENTRIES = 200

README_NAMES = {"readme.md", "readme.rst", "readme.txt", "readme"}
MANIFEST_NAMES = {"pyproject.toml", "setup.py", "package.json", "go.mod", "cargo.toml"}
ENTRYPOINT_NAMES = {
    "__main__.py", "main.py", "cli.py", "app.py", "server.py",
    "run.py", "manage.py", "index.js", "index.ts",
}


def _prune_dirs(dirpath: str, dirnames: list[str]) -> list[str]:
    """Sorted, non-skipped, non-symlinked subdirectory names.

    Symlinked directories are dropped: an untrusted repo could symlink a
    directory to host data, and following it would leak files outside the repo
    into the summaries (and create inconsistent traversal)."""
    return sorted(
        d for d in dirnames
        if not should_skip_dir(d) and not os.path.islink(os.path.join(dirpath, d))
    )


def _read_text_safe(path: str, limit: int = MAX_FILE_CHARS) -> str:
    # Refuse symlinks: an untrusted repo can point a file at host data such as
    # ../../.env, which would otherwise be read and sent to the model.
    if os.path.islink(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(limit + 1)
    except OSError:
        return ""
    if len(text) > limit:
        text = text[:limit] + "\n... [truncated]"
    return text


def _list_entries(directory: str) -> list[str]:
    """Non-skipped, non-symlinked entries (files + dirs) of a directory, sorted."""
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    out = []
    for name in names:
        full = os.path.join(directory, name)
        if os.path.islink(full):  # never follow symlinks (see _read_text_safe)
            continue
        if os.path.isdir(full):
            if not should_skip_dir(name):
                out.append(name)
        elif not should_skip_file(name):
            out.append(name)
    return out


def _all_files(root: str):
    """Yield every non-skipped, non-symlinked file path under root (recursive)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = _prune_dirs(dirpath, dirnames)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if not should_skip_file(name) and not os.path.islink(full):
                yield full


def _find_entrypoints(root: str) -> list[str]:
    """Likely front-door files (depth <= 2) — the human's first read when there
    is no README."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = _prune_dirs(dirpath, dirnames)
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > 2:
            dirnames[:] = []
            continue
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if name.lower() in ENTRYPOINT_NAMES and not os.path.islink(full):
                found.append(full)
    return found[:MAX_ENTRYPOINTS]


def _build_root_content(root: str) -> str:
    """Orientation content: README (if any) + manifests + entry-points + tree.

    Dependencies are the strongest domain signal when a README is absent, so the
    manifest is always included and flagged as such.
    """
    parts: list[str] = []

    for name in _list_entries(root):
        low = name.lower()
        if low in README_NAMES:
            parts.append(f"# {name}\n{_read_text_safe(os.path.join(root, name))}")
        elif low in MANIFEST_NAMES:
            parts.append(
                f"# {name} (manifest — dependencies are a strong domain signal)\n"
                f"{_read_text_safe(os.path.join(root, name))}"
            )

    for ep in _find_entrypoints(root):
        rel = os.path.relpath(ep, root)
        parts.append(f"# entry point: {rel}\n{_read_text_safe(ep, MAX_ENTRYPOINT_CHARS)}")

    # Recursive structure listing — bounded (depth + entry count) so a large
    # repo's path listing can't blow the context window.
    tree: list[str] = []
    extra = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = _prune_dirs(dirpath, dirnames)
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        files = [f for f in sorted(filenames) if not should_skip_file(f)]
        if depth > MAX_TREE_DEPTH or len(tree) >= MAX_TREE_ENTRIES:
            extra += len(files)
            dirnames[:] = []  # stop descending this branch
            continue
        indent = "  " * depth
        base = "." if rel == "." else os.path.basename(dirpath)
        tree.append(f"{indent}{base}/")
        for name in files:
            if len(tree) >= MAX_TREE_ENTRIES:
                extra += 1
            else:
                tree.append(f"{indent}  {name}")
    if extra:
        tree.append(f"  ... (+{extra} more files/dirs not shown)")
    parts.append("# structure\n" + "\n".join(tree))

    content = "\n\n".join(parts)
    # Aggregate budget: README/manifests/entry-points come first, so truncating
    # the tail sheds the structure listing before any higher-signal content.
    if len(content) > MAX_ROOT_CONTENT_CHARS:
        content = content[:MAX_ROOT_CONTENT_CHARS] + "\n... [truncated]"
    return content


def _rel(path: str, root: str) -> str:
    r = os.path.relpath(path, root)
    return REPO_PATH if r == "." else r


def summarize_repo(root: str, summarize_fn, repo_name: str) -> list[dict]:
    """Recursively summarize a repo into intent artifacts (see module docstring).

    `summarize_fn` is the level-dispatching callable from
    `summarize.make_summarize_fn`, called as
    summarize_fn(level, *, path, content, root, parent, files, submods).
    """
    # --- 1. provisional root (framing scaffold) ---
    root_prov = summarize_fn(
        "root_provisional", path=REPO_PATH, content=_build_root_content(root)
    )

    # --- 2. leaves: every file, framed by the provisional root ---
    leaf_intents: dict[str, str] = {}  # relpath -> intent
    for file_path in _all_files(root):
        rel = _rel(file_path, root)
        leaf_intents[rel] = summarize_fn(
            "leaf", path=rel, content=_read_text_safe(file_path), root=root_prov
        )

    # --- 3. modules: top-down (parent summary computed before children) ---
    module_artifacts: list[dict] = []

    def _do_module(directory: str, parent_summary: str | None, parent_path: str) -> None:
        entries = _list_entries(directory)
        files = [e for e in entries if os.path.isfile(os.path.join(directory, e))]
        subdirs = [e for e in entries if os.path.isdir(os.path.join(directory, e))]

        # Collapse fileless structural directories: a dir with no files of its
        # own has no leaf evidence, so its module summary would be ungrounded
        # (inferred from names/framing only, against the prompt's grounding
        # contract). Skip emitting a node — attach its sub-modules to this dir's
        # parent instead. This subsumes the bare-`src/`-wrapper case (a fileless
        # dir with a single sub-dir) and the multi-subdir structural-dir case.
        if not files:
            for sub in subdirs:
                _do_module(os.path.join(directory, sub), parent_summary, parent_path)
            return

        rel = _rel(directory, root)
        file_block = "\n\n".join(
            f"[{f}]\n{leaf_intents[_rel(os.path.join(directory, f), root)]}" for f in files
        )
        summary = summarize_fn(
            "module",
            path=rel,
            root=root_prov,
            parent=parent_summary,
            files=file_block,
            submods=", ".join(subdirs),
        )
        module_artifacts.append(
            {"repo": repo_name, "path": rel, "level": "module",
             "parent_path": parent_path, "intent": summary}
        )
        for sub in subdirs:
            _do_module(os.path.join(directory, sub), summary, rel)

    for entry in _list_entries(root):
        full = os.path.join(root, entry)
        if os.path.isdir(full):
            _do_module(full, None, REPO_PATH)

    # --- leaf artifacts (parent = the module directly containing the file) ---
    file_artifacts: list[dict] = []
    for rel, intent in leaf_intents.items():
        directory = os.path.dirname(rel)
        parent_path = REPO_PATH if directory == "" else directory
        file_artifacts.append(
            {"repo": repo_name, "path": rel, "level": "file",
             "parent_path": parent_path, "intent": intent}
        )

    # --- 4. root final: re-derive from the top-level modules/files ---
    top_children: list[str] = []
    for m in module_artifacts:
        if m["parent_path"] == REPO_PATH:
            top_children.append(f"[module {m['path']}/]\n{m['intent']}")
    for f in file_artifacts:
        if f["parent_path"] == REPO_PATH:
            top_children.append(f"[file {f['path']}]\n{f['intent']}")

    root_final = summarize_fn(
        "root_final", path=REPO_PATH, parent=root_prov, files="\n\n".join(top_children)
    )

    repo_artifact = {
        "repo": repo_name, "path": REPO_PATH, "level": "repo",
        "parent_path": None, "intent": root_final,
    }

    return [repo_artifact] + module_artifacts + file_artifacts


def summarize_repo_incremental(
    root: str, summarize_fn, repo_name: str, *,
    cache: dict[str, str], changed: set[str] | None = None,
    force_modules: set[str] | None = None, module_change_ratio: float = 0.0,
) -> list[dict]:
    """Change-aware `summarize_repo`: reuse cached summaries, call the model ONLY for
    nodes that actually changed (spec §15 partial re-ingestion).

    - `cache`: {relpath -> prior intent} for leaves, modules, and the root (REPO_PATH).
      Typically the stored docs of a prior scan.
    - `changed`: leaf relpaths known to have changed (from a git diff). None => treat
      every leaf as changed (a full pass; used on the first scan / no prior sha).
    - `force_modules`: module/root relpaths to re-summarize regardless (e.g. the parent
      dirs of deleted files, whose summaries still mention the gone file).
    - `module_change_ratio`: re-summarize a module only when the fraction of its DIRECT
      files that changed >= this. 0.0 (default) => any changed direct file re-summarizes
      it (always fresh); >0 trades freshness for fewer summary calls.

    Dirtiness propagates by the SAME data flow summarize_repo uses: a module's evidence is
    its direct files only, and the root's evidence is the top-level modules/files — so a
    node is re-summarized exactly when one of its own evidence items changed. Unchanged
    nodes carry their cached intent (byte-identical), so the caller's content_hash check
    skips re-persisting them. Returns the full artifact list, same contract as summarize_repo.
    """
    force_modules = force_modules or set()
    _prov = {"v": None}

    def root_prov():
        if _prov["v"] is None:
            _prov["v"] = summarize_fn("root_provisional", path=REPO_PATH, content=_build_root_content(root))
        return _prov["v"]

    # --- leaves: summarize only changed / new / uncached files ---
    leaf_intents: dict[str, str] = {}
    leaf_dirty: dict[str, bool] = {}
    for file_path in _all_files(root):
        rel = _rel(file_path, root)
        fresh = (changed is None) or (rel not in cache) or (rel in changed)
        if fresh:
            leaf_intents[rel] = summarize_fn("leaf", path=rel, content=_read_text_safe(file_path), root=root_prov())
            leaf_dirty[rel] = True
        else:
            leaf_intents[rel] = cache[rel]
            leaf_dirty[rel] = False

    module_artifacts: list[dict] = []
    resummarized_modules: set[str] = set()

    def _do_module(directory: str, parent_summary: str | None, parent_path: str) -> None:
        entries = _list_entries(directory)
        files = [e for e in entries if os.path.isfile(os.path.join(directory, e))]
        subdirs = [e for e in entries if os.path.isdir(os.path.join(directory, e))]
        if not files:
            for sub in subdirs:
                _do_module(os.path.join(directory, sub), parent_summary, parent_path)
            return

        rel = _rel(directory, root)
        file_rels = [_rel(os.path.join(directory, f), root) for f in files]
        changed_here = [fr for fr in file_rels if leaf_dirty.get(fr)]
        frac = len(changed_here) / max(1, len(file_rels))

        must = (rel not in cache) or (rel in force_modules)
        if must or (changed_here and frac >= module_change_ratio):
            summary = summarize_fn("module", path=rel, root=root_prov(),
                                   parent=parent_summary, files="\n\n".join(
                                       f"[{f}]\n{leaf_intents[_rel(os.path.join(directory, f), root)]}" for f in files),
                                   submods=", ".join(subdirs))
            resummarized_modules.add(rel)
        else:
            summary = cache[rel]   # reuse (nothing beneath changed, or below threshold)

        module_artifacts.append(
            {"repo": repo_name, "path": rel, "level": "module",
             "parent_path": parent_path, "intent": summary})
        for sub in subdirs:
            _do_module(os.path.join(directory, sub), summary, rel)

    for entry in _list_entries(root):
        full = os.path.join(root, entry)
        if os.path.isdir(full):
            _do_module(full, None, REPO_PATH)

    file_artifacts: list[dict] = []
    for rel, intent in leaf_intents.items():
        directory = os.path.dirname(rel)
        parent_path = REPO_PATH if directory == "" else directory
        file_artifacts.append(
            {"repo": repo_name, "path": rel, "level": "file",
             "parent_path": parent_path, "intent": intent})

    # --- root: re-derive only if a top-level child changed (or forced / uncached) ---
    top_children = []
    top_dirty = (REPO_PATH not in cache) or (REPO_PATH in force_modules)
    for m in module_artifacts:
        if m["parent_path"] == REPO_PATH:
            top_children.append(f"[module {m['path']}/]\n{m['intent']}")
            if m["path"] in resummarized_modules:
                top_dirty = True
    for f in file_artifacts:
        if f["parent_path"] == REPO_PATH:
            top_children.append(f"[file {f['path']}]\n{f['intent']}")
            if leaf_dirty.get(f["path"]):
                top_dirty = True

    if top_dirty:
        root_final = summarize_fn("root_final", path=REPO_PATH, parent=root_prov(),
                                  files="\n\n".join(top_children))
    else:
        root_final = cache[REPO_PATH]

    repo_artifact = {"repo": repo_name, "path": REPO_PATH, "level": "repo",
                     "parent_path": None, "intent": root_final}
    return [repo_artifact] + module_artifacts + file_artifacts
