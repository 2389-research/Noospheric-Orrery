# ABOUTME: Vault featurizer — an Obsidian-style note dir -> one SourceDoc per note.
# ABOUTME: Prunes junk dirs (.obsidian/.trash), then parses+cleans each markdown note.
"""source -> iterator[SourceDoc]. The vault adapter for the incremental-source-sync spine."""
import os
from pathlib import Path

from .base import SourceDoc
from .ignore import should_skip_dir, should_skip_file
from .markdown import parse_frontmatter, clean_markdown


def _iter_note_paths(root: Path, exts: set, extra_dirs):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not should_skip_dir(d, extra_dirs))
        for fn in sorted(filenames):
            if Path(fn).suffix.lower() in exts and not should_skip_file(fn):
                yield Path(dirpath) / fn


def _folder_domain(path: Path, root: Path) -> str | None:
    rel = path.parent.relative_to(root)
    parts = [p for p in rel.parts if p]     # note at vault root -> no folder domain
    return "/".join(p.lower() for p in parts) if parts else None


def enumerate_vault(uri: str, config: dict):
    config = config or {}
    exts = {("." + str(e).lstrip(".")).lower() for e in (config.get("ext") or [".md"])}
    extra_dirs = config.get("ignore") or []
    root = Path(uri)
    if not root.exists():
        return
    for f in _iter_note_paths(root, exts, extra_dirs):
        text = f.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)
        body = clean_markdown(body)
        if not body.strip():
            continue
        title = (meta.get("title") if isinstance(meta.get("title"), str) else None) or f.stem
        domain_hint = None
        if config.get("folder_domains"):
            domain_hint = _folder_domain(f, root)
        yield SourceDoc(source_path=str(f), title=title, content=body,
                        emits_cooccurrence=True, metadata=(meta or None),
                        domain_hint=domain_hint)
