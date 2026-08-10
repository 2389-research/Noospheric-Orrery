# ABOUTME: Deterministic post-extraction filter — drops identity-noise entities.
# ABOUTME: Strips file-path names and a unit's own file/module/repo name (not concepts).

"""Identity is not intent.

The graph is built from LLM *summaries* of code, and a summary of `traverse.py`
inevitably mentions `traverse.py`. An entity named after the thing being described
carries no information: it co-occurs with everything in its own document by
construction, so it becomes a hub that connects unrelated neighbourhoods and makes
the map worse the more of the repo you ingest.

Deterministic rather than prompted. Asking the extractor to avoid self-names works
most of the time, which is the problem — the failures are silent, unevenly
distributed across models, and each one is a permanent hub node in the graph.
"""

# An entity name ending in a source extension is a path, not a concept.
SOURCE_EXTS = (
    ".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".gd", ".go", ".java", ".rb",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".php", ".swift", ".kt", ".scala", ".vue",
    ".svelte", ".toml", ".cfg", ".ini", ".lock", ".md",
)


def _identity_names(doc_path: str = "", collection_name: str = "") -> set[str]:
    """The names that ARE this unit, in the spellings a model actually emits."""
    out: set[str] = set()
    if collection_name:
        c = collection_name.lower().strip()
        # Normalize to ONE separator first, then derive every spelling from that.
        # Deriving them from the input directly only covered names that already
        # contained the separator being replaced: `demo-repo` yielded `demo repo`,
        # but `demo_repo` never did — so whether a repo's own name was filtered
        # depended on how it happened to be punctuated.
        base = c.replace("_", "-").replace(" ", "-")
        out |= {c, base, base.replace("-", "_"), base.replace("-", " ")}
    if doc_path and doc_path != ".":
        p = doc_path.lower().strip()
        out.add(p)
        basename = p.rsplit("/", 1)[-1]
        out.add(basename)
        # The module stem, not just the filename. A summary of `traverse.py` names the
        # unit `traverse` about as often as `traverse.py`, and that entity is identity
        # for the same reason: it co-occurs with everything in this document by
        # construction. Gated on a known source extension so a path like
        # `notes.2026.md` does not also contribute `notes.2026`.
        #
        # This does drop a stem that reads like a real concept (`parser` inside
        # `parser.py`). That is the intended trade: within its own file the name adds
        # no differentiating information, and a concept that genuinely matters also
        # appears in the sibling and parent summaries, where it is not identity and
        # survives.
        stem, _, ext = basename.rpartition(".")
        if stem and f".{ext}" in SOURCE_EXTS:
            out.add(stem)
    return out


def is_identity_noise(name: str, doc_path: str = "", collection_name: str = "") -> bool:
    """True if `name` is a file path or the unit's own file/module/collection name."""
    n = name.lower().strip()
    if not n:
        return True
    if n.endswith(SOURCE_EXTS):  # the entity name is a file path, not a concept
        return True
    return n in _identity_names(doc_path, collection_name)
