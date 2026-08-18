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


_COMMENT_RE = re.compile(r"%%.*?%%", re.DOTALL)
_EMBED_RE = re.compile(r"!\[\[[^\]]*\]\]")          # image/note embeds -> dropped
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")       # [[target(#heading)?(|display)?]]


def _wikilink_text(m: "re.Match") -> str:
    inner = m.group(1)
    if "|" in inner:                # [[target|display]] -> display
        return inner.split("|", 1)[1]
    return inner.split("#", 1)[0]   # [[target#heading]] -> target


def clean_markdown(text: str) -> str:
    """Strip Obsidian comments/embeds and reduce wikilinks to their visible text."""
    text = _COMMENT_RE.sub("", text)
    text = _EMBED_RE.sub("", text)          # must run before the wikilink sub
    return _WIKILINK_RE.sub(_wikilink_text, text)
