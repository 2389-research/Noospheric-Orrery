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
        # Separator variants: a model asked about `demo-repo` will happily write
        # `demo_repo` or `demo repo`, and all three are the same identity.
        out |= {c, c.replace("-", "_"), c.replace("_", "-"), c.replace("-", " ")}
    if doc_path and doc_path != ".":
        p = doc_path.lower().strip()
        out.add(p)
        out.add(p.rsplit("/", 1)[-1])  # basename
    return out


def is_identity_noise(name: str, doc_path: str = "", collection_name: str = "") -> bool:
    """True if `name` is a file path or the unit's own file/module/collection name."""
    n = name.lower().strip()
    if not n:
        return True
    if n.endswith(SOURCE_EXTS):  # the entity name is a file path, not a concept
        return True
    return n in _identity_names(doc_path, collection_name)
