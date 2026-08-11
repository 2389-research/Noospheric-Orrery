"""The run's spec artifacts — read verbatim, never summarized.

A spec is already prose written for a reader, so summarizing it would only lose
information. It is carried through as `text` (for classification and extraction) plus a
fingerprint, which is what makes two runs in a chain comparable: same fingerprint = the
same problem statement, different fingerprint = the spec was perturbed.
"""
from __future__ import annotations

import hashlib
import os

# Broad -> specific, and `gather_spec` concatenates in exactly this order: a brief is
# refined by a spec, refined by a contract, refined by per-unit specs. Reading order for
# a human, and the order the classifier sees. This tuple's order is part of the output —
# reordering it changes every `text` and therefore every `fingerprint`, so two corpora
# summarized under different orders would stop being comparable. Pinned by a test.
SPEC_ARTIFACTS = ("BRIEF.md", "SPEC.md", ".flagship/CONTRACT.md", ".flagship/UNIT-SPECS.md")


def working_dir_of(run_dir: str) -> str:
    """The checkout dir a run executed in (everything above `/.tracker/`).

    Spec artifacts live in the checkout, not in the run's own output dir.
    """
    return run_dir.split(os.sep + ".tracker" + os.sep)[0]


def gather_spec(working_dir: str, artifacts: tuple[str, ...] = SPEC_ARTIFACTS) -> dict:
    """Collect whichever spec artifacts exist, concatenated in `artifacts` order.

    Returns {artifacts, chars, text, fingerprint}. `text` is embedded rather than left
    as a path reference so the summary bundle is self-contained — it has to be readable
    from inside a container that never sees the original checkout. Note `artifacts` is
    sorted for stable reporting, so it does NOT necessarily match the `text` order.
    """
    found: dict[str, str] = {}
    for rel in artifacts:
        p = os.path.join(working_dir, rel)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    found[rel] = f.read()
            except OSError:
                continue
    text = "\n\n".join(found.values())
    return {
        "artifacts": sorted(found),
        "chars": len(text),
        "text": text,
        "fingerprint": hashlib.sha256(text.encode()).hexdigest()[:16] if text else None,
    }
