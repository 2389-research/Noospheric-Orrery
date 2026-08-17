# ABOUTME: Pure Obsidian-markdown helpers — frontmatter split + wikilink/comment cleaning.
# ABOUTME: No I/O; safe on malformed input (never raises).
import re

import yaml

_FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def parse_frontmatter(text: str):
    """Return (metadata_dict, body). No frontmatter -> ({}, text). Bad YAML -> ({}, body)."""
    text = text.replace("\r\n", "\n")   # a Windows-edited vault uses CRLF; the LF-only
                                        # regex would otherwise miss the block and leak it
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        meta = None
    if not isinstance(meta, dict):
        meta = {}
    return meta, text[m.end():]
