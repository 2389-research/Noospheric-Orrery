"""Deterministic faithfulness check on a node summary — no second model call.

Every file path a summary names must appear in the trace it was summarized from. A path
that does not is a hallucination, and it is cheap to catch exactly because paths are
mechanically extractable. This is the check that makes a small model trustworthy enough
to summarize at scale: not "does it read well" but "did it invent an artifact."
"""
from __future__ import annotations

import re

# File-ish tokens. Extensions are the ones tracker runs actually produce; a path with
# an unlisted extension is simply not checked (the check is a floor, not a ceiling).
# The optional leading dot keeps dotfile paths intact (`.flagship/gate/001.log`) — an
# earlier version anchored on \w and reported them without it.
# Anchored on a NON-path character (or start) on the left, and a non-path character on
# the right, so a token is matched WHOLE. `\b` accepted the boundary before a dot, which
# meant `src/store.js` in the trace marked the INVENTED `src/store.js.bak` as grounded —
# defeating the one thing this check exists to catch.
#
# The extension list is the floor, not the ceiling, but it now covers the artifacts
# tracker runs actually name: `workflow.dip`, config/CI yaml, and extensionless files
# (Dockerfile, Makefile) which were invisible to an extension-only pattern.
_EXTS = "js|mjs|ts|tsx|json|md|py|txt|log|tsv|csv|yml|yaml|toml|dip|sh|rs|go"
_EXTENSIONLESS = "Dockerfile|Makefile|Procfile|LICENSE|README"
PATH_RE = re.compile(
    r"(?<![\w./-])"                                   # not mid-token on the left
    r"(?:"
    rf"\.?[\w][\w./-]*\.(?:{_EXTS})"                 # dotted paths, known extension
    rf"|(?:[\w./-]*/)?(?:{_EXTENSIONLESS})"            # extensionless, optionally in a dir
    r")"
    # Reject a token that CONTINUES on the right — but a sentence-final dot is not a
    # continuation. `(?![\w./-])` alone rejected "wrote src/store.js." and matched
    # nothing; this rejects `/foo`, `-bar` and `.bak` while allowing a terminal dot,
    # which `paths_in` then strips.
    r"(?![\w/-])(?!\.\w)"
)


def paths_in(text: str) -> set[str]:
    """File paths mentioned anywhere in `text`.

    Trailing dots only ("wrote foo.js." -> "foo.js"); a LEADING dot is part of the path,
    so dotfiles keep it (`.flagship/gate/001.log`). Stripping both ends — as an earlier
    version did — still produced correct verdicts, since the same normalization applies
    to trace and summary alike, but it misreported dotfile paths in `ungrounded`.
    """
    return {p.rstrip(".") for p in PATH_RE.findall(text)}


def check_grounding(summary: str, trace: str) -> dict:
    """{named, grounded, ungrounded} — ungrounded paths are the hallucinations.

    `ungrounded` is sorted so a run's output is stable across invocations.
    """
    src, got = paths_in(trace), paths_in(summary)
    return {
        "named": len(got),
        "grounded": len(got & src),
        "ungrounded": sorted(got - src),
    }
