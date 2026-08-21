# ABOUTME: Pure metric functions M1-M5 over collected DocResults. No I/O, no LLM, so the
# ABOUTME: A/B decision arithmetic is unit-tested in CI while collection stays out of it.
import statistics
from collections import defaultdict
from collections.abc import Sequence

from .models import DocResult


def filter_variant(docs: Sequence[DocResult], variant: str) -> list[DocResult]:
    return [d for d in docs if d.variant == variant]


def _docs_by_name(docs: Sequence[DocResult], type_: str) -> dict[str, set[str]]:
    """name -> set of distinct doc_ids it appeared in.

    Keyed on doc_id, NOT on (doc_id, repeat): repeats of one document are the same
    document, and counting them would make every name look mergeable.
    """
    out: dict[str, set[str]] = defaultdict(set)
    for d in docs:
        for name in d.names_for(type_):
            out[name].add(d.doc_id)
    return out


def mergeability(docs: Sequence[DocResult], type_: str) -> float:
    """M1 — fraction of distinct names of `type_` that appear in 2+ distinct documents."""
    by_name = _docs_by_name(docs, type_)
    if not by_name:
        return 0.0
    shared = sum(1 for doc_ids in by_name.values() if len(doc_ids) >= 2)
    return shared / len(by_name)


def median_name_words(docs: Sequence[DocResult], type_: str) -> float:
    """M2 — median word count over DISTINCT names (a name repeated 40x is one shape)."""
    names = {n for d in docs for n in d.names_for(type_)}
    if not names:
        return 0.0
    return float(statistics.median(len(n.split()) for n in names))


def volume_per_doc(docs: Sequence[DocResult], type_: str) -> float:
    """M3 — mean count of `type_` per distinct document, averaging repeats first."""
    per_doc: dict[str, list[int]] = defaultdict(list)
    for d in docs:
        per_doc[d.doc_id].append(len(d.names_for(type_)))
    if not per_doc:
        return 0.0
    return float(statistics.mean(statistics.mean(v) for v in per_doc.values()))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return 1.0 if not union else len(a & b) / len(union)


def type_stability(docs: Sequence[DocResult], doc_id: str) -> float:
    """M4 — mean pairwise Jaccard of the fired-type set across repeats of one document."""
    sets = [d.fired_types() for d in docs if d.doc_id == doc_id]
    if len(sets) < 2:
        return 1.0
    pairs = [_jaccard(sets[i], sets[j])
             for i in range(len(sets)) for j in range(i + 1, len(sets))]
    return float(statistics.mean(pairs))


def count_cv(docs: Sequence[DocResult], doc_id: str, type_: str) -> float:
    """M5 — coefficient of variation of per-type counts across repeats of one document."""
    counts = [len(d.names_for(type_)) for d in docs if d.doc_id == doc_id]
    if len(counts) < 2:
        return 0.0
    mean = statistics.mean(counts)
    if mean == 0:
        return 0.0
    return float(statistics.pstdev(counts) / mean)
