"""File/directory selection policy for the Phase 1 traversal.

Decides what gets skipped entirely (noise, generated artifacts, binaries,
secrets) versus what should get a file artifact.
"""
from __future__ import annotations

import os

SKIP_DIR_NAMES = {
    "node_modules",
    "dist",
    "build",
    "target",     # Rust/Java/Scala build output
    "out",         # common JS/Java build output
    ".venv",
    "venv",
    "vendor",
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "egg-info",
}

SKIP_FILE_SUFFIXES = {
    ".lock",
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".whl",
}

SKIP_FILE_NAMES = {
    "uv.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Pipfile.lock",
    "poetry.lock",
    "Cargo.lock",
    "go.sum",
}


def should_skip_dir(name: str) -> bool:
    """Return True if a directory (by its basename) should be skipped entirely."""
    if name.startswith("."):
        # Hidden dirs are config/CI/build/cache artifacts, not source intent:
        # .git, .godot, .next, .idea, .vscode, .cache, .pytest_cache, ... Mirrors
        # should_skip_file's dotfile rule. (Without this, e.g. a Godot project's
        # .godot/shader_cache blows up into dozens of compiled-shader "modules".)
        return True
    if name in SKIP_DIR_NAMES:
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def should_skip_file(name: str) -> bool:
    """Return True if a file (by its basename) should be skipped entirely."""
    if name.startswith("."):
        # dotfiles like .env, .gitignore, .DS_Store
        return True
    if name in SKIP_FILE_NAMES:
        return True
    # Case-folded: the skip list is lowercase, but filesystems are not. `diagram.PNG`
    # and `bundle.ZIP` were sailing past it, so binary and archive bytes reached the
    # summarizer — and on a case-insensitive filesystem the same file skips or not
    # depending purely on how it happens to be spelled.
    _, ext = os.path.splitext(name)
    if ext.lower() in SKIP_FILE_SUFFIXES:
        return True
    return False


# Backwards/simple-name alias matching the design doc's "should_skip(path)" mention.
def should_skip(path: str) -> bool:
    """Generic skip check usable on either a file or directory basename/path."""
    name = os.path.basename(path.rstrip(os.sep))
    if os.path.isdir(path):
        return should_skip_dir(name)
    return should_skip_file(name)
