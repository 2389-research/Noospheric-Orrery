# ABOUTME: Stratified sampling for M6 precision, which only a human can measure. Seeded
# ABOUTME: so re-running does not invalidate labels already applied to a previous sample.
import csv
import random
from collections import defaultdict
from collections.abc import Sequence

from .models import DocResult

FIELDNAMES = ["doc_id", "type", "name", "correct"]


def stratified_sample(docs: Sequence[DocResult], per_type: int = 25,
                      seed: int = 42) -> list[dict]:
    """Up to `per_type` distinct (doc_id, name) pairs per type, for hand-labelling.

    The default is 25, not 10: M6 for `obligation` is judged against a 0.80 threshold,
    and 10 labels can only ever express multiples of 0.10 — they cannot distinguish
    0.80 from 0.79.
    """
    pool: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for d in docs:
        for t in d.types:
            for name in t.names:
                pool[t.type].add((d.doc_id, name))
    rng = random.Random(seed)
    rows: list[dict] = []
    for type_ in sorted(pool):
        items = sorted(pool[type_])
        picked = items if len(items) <= per_type else rng.sample(items, per_type)
        for doc_id, name in sorted(picked):
            rows.append({"doc_id": doc_id, "type": type_, "name": name, "correct": ""})
    return rows


def write_csv(rows: Sequence[dict], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def precision_from_csv(path: str, type_: str | None = None) -> float:
    yes = no = 0
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if type_ is not None and row["type"] != type_:
                continue
            label = (row.get("correct") or "").strip().lower()
            if label == "y":
                yes += 1
            elif label == "n":
                no += 1
    total = yes + no
    return 0.0 if total == 0 else yes / total
