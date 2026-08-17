# ABOUTME: Vault featurizer — an Obsidian-style note dir -> one document per note.
# ABOUTME: Notes are flat leaves (no hierarchy), so every note emits co-occurrence.
"""source -> iterator[(source_path, title, content, emits_cooccurrence)].

The vault adapter for the incremental-source-sync spine (spec 2026-08-14 §11). A note
maps to ONE document: `source_path` is the file path as the worker sees it (staged under
the data mount), `title` is the file stem, `content` is the file text. Empty files are
skipped. `emits_cooccurrence` is always True — notes are flat leaves, not a summary
hierarchy, so their pairwise co-occurrence is signal, not noise.
"""
from pathlib import Path


def enumerate_vault(uri: str, config: dict):
    """Yield (source_path, title, content, emits_cooccurrence) for each non-empty note.

    `config["ext"]` overrides the extension filter (default `[".md"]`); values may be
    given with or without the leading dot. Files are yielded in sorted path order so a
    scan is deterministic.
    """
    config = config or {}
    exts = {("." + str(e).lstrip(".")).lower() for e in (config.get("ext") or [".md"])}
    root = Path(uri)
    if not root.exists():
        return
    for f in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts):
        text = f.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        yield (str(f), f.stem, text, True)
