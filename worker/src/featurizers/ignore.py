# ABOUTME: Shared path-ignore policy for filesystem-walking featurizers (vault, hot folder).
# ABOUTME: Defaults mirror orrery-codesum's fileselect; per-source config["ignore"] extends them.
"""A gitignore-equivalent for ingestion.

Defaults skip any dotfolder (so `.obsidian/` and `.trash/` never ingest), common caches,
and binary/attachment suffixes (text-only MVP). A source's config may extend the skipped
directory names via `config["ignore"]`.
"""
import os

DEFAULT_SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", "__pycache__"}
DEFAULT_SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".mp3", ".mp4", ".mov",
}


def should_skip_dir(name: str, extra_dirs=()) -> bool:
    """Skip any dotfolder, the curated defaults, and any name the source configured."""
    return name.startswith(".") or name in DEFAULT_SKIP_DIRS or name in set(extra_dirs)


def should_skip_file(name: str, extra_suffixes=()) -> bool:
    """Skip binaries/attachments by suffix (case-folded)."""
    _, ext = os.path.splitext(name)
    return ext.lower() in (DEFAULT_SKIP_SUFFIXES | set(extra_suffixes))
