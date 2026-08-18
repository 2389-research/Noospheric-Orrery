# ABOUTME: SourceDoc — the extensible output contract a featurizer yields to the sync spine.
# ABOUTME: Replaces the positional 4-tuple so new fields (metadata, hints) are additive.
"""One record per document a source produces.

A featurizer yields SourceDoc instances; scan_source coerces + upserts each. Legacy
featurizers/fixtures that still yield a 3- or 4-tuple are accepted via SourceDoc.coerce,
so adding fields never breaks an unpack site.
"""
from dataclasses import dataclass


@dataclass
class SourceDoc:
    source_path: str
    title: str
    content: str
    emits_cooccurrence: bool = True
    metadata: dict | None = None      # provenance (e.g. parsed frontmatter); JSON-stored on the doc
    domain_hint: str | None = None    # if set, used as the doc's domain (skips LLM classification)

    @classmethod
    def coerce(cls, item):
        """Accept a SourceDoc or a legacy (path, title, content[, emits]) tuple."""
        if isinstance(item, cls):
            return item
        source_path, title, content, *rest = item
        emits = rest[0] if rest else True
        return cls(source_path=source_path, title=title, content=content,
                   emits_cooccurrence=emits)
