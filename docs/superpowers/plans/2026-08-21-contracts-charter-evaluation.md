# Contracts Charter Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decide, from measured evidence, whether the `business/legal-compliance/contracts` charter ships as variant A (11 types, `obligation`/`condition_trigger` deleted) or variant B (13 types, obligation names constrained to ≤6 words) — then record the verdict.

**Architecture:** `POST /ingest?dry_run=true` already runs the real classifier and real extractor against the real charter spec and writes nothing, so the evaluation harness exercises the production path with zero graph side effects. One small production change is needed first: the dry-run truncates entity names to 3 examples per type, which makes cross-document mergeability uncomputable. After that, all metric computation is **pure functions over collected JSON**, unit-tested in CI; only the collection step needs a live LLM and it stays out of pytest.

**Tech Stack:** Python 3.12, FastAPI, pytest, `curl`/`httpx` against a locally running orchestrator (port 8000), SQLite. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-21-contracts-charter-evaluation-design.md`

## Global Constraints

- **Base commit:** `833eb05`. Record this SHA in the experiment README.
- **Never re-test pipeline wiring.** `test_charter_route.py`, `test_extraction_plan.py`, and `test_domain_normalizer.py` already cover all four charter hook points. Adding overlapping tests is a plan violation.
- **Metric code must be pure and unit-tested.** No live LLM call inside any `pytest` test. The harness injects its transport as a callable.
- **The decision rule is pre-registered and frozen:** ship B iff `obligation` scores M1 ≥ 0.30 **and** M2 ≤ 6 words **and** M6 ≥ 0.80. Otherwise ship A. Do not adjust thresholds after seeing results.
- **Corpus documents are never committed.** Per `experiments/README.md`, regenerable artifacts live in DS-scratch and are referenced by manifest path.
- **Every dry-run call must be verified to have written nothing** (Task 4 asserts this once; do not assume it thereafter).
- **Domain path format:** `/` separator, treated as a hierarchical key, not a filesystem path.
- **All Claude calls go through `orrery-relay`.** The harness never instantiates an Anthropic client; it calls the orchestrator over HTTP.

---

## File Structure

| File | Responsibility |
|---|---|
| `orchestrator/src/models.py:70-73` (modify) | Add `names: list[str] = []` to `DryRunEntityType`. |
| `orchestrator/src/routes/ingest.py:213,262,405` (modify) | Thread a `full_names: bool = False` query param into `_dry_run_document`; populate `names` only when set. |
| `orchestrator/tests/test_dry_run_full_names.py` (create) | Tests for the new param: off by default, full list when on. |
| `scripts/charter_eval/__init__.py` (create) | Package marker. |
| `scripts/charter_eval/models.py` (create) | `TypeResult`, `DocResult` dataclasses — the harness/metrics contract. |
| `scripts/charter_eval/metrics.py` (create) | Pure metric functions M1–M5. No I/O. |
| `scripts/charter_eval/harness.py` (create) | Collection: manifest → dry-run calls → `list[DocResult]` → JSON. Transport injected. |
| `scripts/charter_eval/report.py` (create) | Render collected results as the decision table; apply the pre-registered rule. |
| `scripts/charter_eval/sample.py` (create) | Stratified precision sample (M6) → CSV for hand-labelling. |
| `scripts/charter_eval/__main__.py` (create) | CLI: `collect`, `report`, `sample`. |
| `scripts/charter_eval/tests/test_metrics.py` (create) | Unit tests for M1–M5. |
| `scripts/charter_eval/tests/test_report.py` (create) | Unit tests for the decision rule. |
| `scripts/charter_eval/tests/test_harness.py` (create) | Harness tests with a fake transport. |
| `scripts/charter_eval/corpus.example.json` (create) | Manifest schema, with the two known documents. |
| `orchestrator/specs/contracts_charter_v2a.md` (create) | Variant A spec. |
| `orchestrator/specs/contracts_charter_v2b.md` (create) | Variant B spec. |
| `experiments/2026-08-21-contracts-charter-ab/README.md` (create) | The lab-notebook record. |
| `experiments/README.md` (modify) | Add the index row. |

Decomposition rationale: `metrics.py` is pure and therefore the only part worth heavy TDD; `harness.py` is I/O and gets a fake transport; `report.py` holds the decision rule alone so the frozen thresholds live in exactly one place and a diff to them is visible in review.

---

### Task 1: Expose full entity names from the dry-run

The dry-run truncates to `examples[:3]`, so M1 (mergeability) and M2 (name length) cannot be computed. Add an opt-in param. Default off keeps every existing response byte-identical.

**Files:**
- Modify: `orchestrator/src/models.py:70-73`
- Modify: `orchestrator/src/routes/ingest.py:213`, `:262`, `:405-434`
- Test: `orchestrator/tests/test_dry_run_full_names.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET`-able query param `full_names: bool` on `POST /ingest?dry_run=true`. Response `entity_types[].names: list[str]` — the **untruncated, non-deduplicated** name list for that type, in extraction order. Empty list when `full_names` is false.

- [ ] **Step 1: Write the failing tests**

```python
# orchestrator/tests/test_dry_run_full_names.py
# ABOUTME: The dry-run truncates examples to 3, which makes cross-document mergeability
# ABOUTME: uncomputable. `full_names=true` opts into the untruncated list.
import io
import pytest
from unittest.mock import patch


def _upload(client, body: bytes, *, full_names: bool):
    url = "/ingest?dry_run=true" + ("&full_names=true" if full_names else "")
    return client.post(url, files={"file": ("c.txt", io.BytesIO(body), "text/plain")})


FAKE_ENTITIES = [
    {"name": "tenant — pay monthly rent", "type": "obligation"},
    {"name": "tenant — maintain insurance", "type": "obligation"},
    {"name": "tenant — pay monthly rent", "type": "obligation"},  # duplicate on purpose
    {"name": "tenant — surrender premises", "type": "obligation"},
    {"name": "indemnification", "type": "clause"},
]


@pytest.fixture
def stub_pipeline():
    with patch("src.routes.ingest.classify_document") as clf, \
         patch("src.routes.ingest.extract_document") as ext:
        async def _clf(**kw):
            return {"primary_domain": "business/legal-compliance/contracts",
                    "secondary_domains": [], "confidence": 0.9}
        async def _ext(**kw):
            return list(FAKE_ENTITIES)
        clf.side_effect = _clf
        ext.side_effect = _ext
        yield


def test_names_absent_by_default(test_client, stub_pipeline):
    r = _upload(test_client, b"lease text " * 50, full_names=False)
    assert r.status_code == 200
    by_type = {t["type"]: t for t in r.json()["entity_types"]}
    assert by_type["obligation"]["count"] == 4
    assert by_type["obligation"]["examples"] == [
        "tenant — pay monthly rent",
        "tenant — maintain insurance",
        "tenant — surrender premises",
    ], "examples stay deduped and capped at 3"
    assert by_type["obligation"]["names"] == [], "names must be opt-in"


def test_full_names_returns_every_name_including_duplicates(test_client, stub_pipeline):
    r = _upload(test_client, b"lease text " * 50, full_names=True)
    assert r.status_code == 200
    by_type = {t["type"]: t for t in r.json()["entity_types"]}
    names = by_type["obligation"]["names"]
    assert len(names) == 4, "not deduplicated — count and names must agree"
    assert names.count("tenant — pay monthly rent") == 2
    assert by_type["clause"]["names"] == ["indemnification"]


def test_full_names_does_not_change_the_other_fields(test_client, stub_pipeline):
    plain = _upload(test_client, b"lease text " * 50, full_names=False).json()
    full = _upload(test_client, b"lease text " * 50, full_names=True).json()
    for key in ("primary_domain", "secondary_domains", "run_general", "specs_applied"):
        assert plain[key] == full[key]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd orchestrator && pytest tests/test_dry_run_full_names.py -v
```

Expected: FAIL — `KeyError: 'names'` on the first two tests. The third should already pass.

- [ ] **Step 3: Add the model field**

```python
# orchestrator/src/models.py — replace lines 70-73
class DryRunEntityType(BaseModel):
    type: str
    count: int
    examples: list[str]
    # Untruncated, non-deduplicated names. Populated only under ?full_names=true, because
    # cross-document mergeability cannot be computed from a 3-item sample. Default empty
    # keeps every existing dry-run response byte-identical.
    names: list[str] = []
```

- [ ] **Step 4: Thread the flag through the route**

```python
# orchestrator/src/routes/ingest.py:213 — change the signature
async def _dry_run_document(store, title: str, content: str,
                            full_names: bool = False) -> dict:
```

```python
# orchestrator/src/routes/ingest.py:261-264 — replace the entity_types comprehension
    entity_types = [
        {"type": t, "count": len(names),
         "examples": list(dict.fromkeys(names))[:3],
         "names": list(names) if full_names else []}
        for t, names in sorted(grouped.items(), key=lambda kv: -len(kv[1]))
    ]
```

```python
# orchestrator/src/routes/ingest.py:408 — add the param next to dry_run
    dry_run: bool = False,
    full_names: bool = False,
```

```python
# orchestrator/src/routes/ingest.py:434 — pass it through
            result = await _dry_run_document(store, title, content, full_names=full_names)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd orchestrator && pytest tests/test_dry_run_full_names.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run the full orchestrator suite for regressions**

```bash
cd orchestrator && pytest tests/ -q
```

Expected: no new failures. `full_names` defaults to false, so existing dry-run tests must be untouched.

- [ ] **Step 7: Commit**

```bash
git add orchestrator/src/models.py orchestrator/src/routes/ingest.py \
        orchestrator/tests/test_dry_run_full_names.py
git commit -m "feat(ingest): add dry_run full_names for charter spec evaluation"
```

---

### Task 2: Harness/metrics data contract

**Files:**
- Create: `scripts/charter_eval/__init__.py`
- Create: `scripts/charter_eval/models.py`

**Interfaces:**
- Consumes: the Task 1 response shape.
- Produces: `TypeResult(type: str, count: int, names: tuple[str, ...])`; `DocResult(doc_id: str, instrument: str, executed: bool, variant: str, repeat: int, primary_domain: str, run_general: bool, specs_applied: tuple[str, ...], latency_s: float, types: tuple[TypeResult, ...])`; `DocResult.names_for(type: str) -> tuple[str, ...]`; `DocResult.from_response(doc_id, instrument, executed, variant, repeat, latency_s, payload: dict) -> DocResult`. Both frozen dataclasses, `to_dict()`/`from_dict()` for JSON round-tripping.

- [ ] **Step 1: Write the failing test**

```python
# scripts/charter_eval/tests/test_models.py
# ABOUTME: The harness/metrics contract — frozen dataclasses that round-trip through JSON.
from charter_eval.models import DocResult, TypeResult

PAYLOAD = {
    "primary_domain": "business/legal-compliance/contracts",
    "secondary_domains": [],
    "confidence": 0.97,
    "run_general": False,
    "specs_applied": ["business/legal-compliance/contracts"],
    "entity_types": [
        {"type": "obligation", "count": 2,
         "examples": ["tenant — pay rent"], "names": ["tenant — pay rent", "tenant — pay rent"]},
        {"type": "clause", "count": 1, "examples": ["indemnification"], "names": ["indemnification"]},
    ],
}


def test_from_response_maps_every_field():
    d = DocResult.from_response("lease-01", "lease", True, "B", 0, 12.5, PAYLOAD)
    assert d.doc_id == "lease-01"
    assert d.instrument == "lease"
    assert d.executed is True
    assert d.variant == "B"
    assert d.run_general is False
    assert d.specs_applied == ("business/legal-compliance/contracts",)
    assert d.latency_s == 12.5
    assert d.names_for("obligation") == ("tenant — pay rent", "tenant — pay rent")
    assert d.names_for("clause") == ("indemnification",)


def test_names_for_absent_type_is_empty():
    d = DocResult.from_response("lease-01", "lease", True, "B", 0, 1.0, PAYLOAD)
    assert d.names_for("governing_law") == ()


def test_json_round_trip():
    d = DocResult.from_response("lease-01", "lease", True, "B", 0, 12.5, PAYLOAD)
    assert DocResult.from_dict(d.to_dict()) == d


def test_type_result_is_frozen():
    import dataclasses, pytest
    t = TypeResult(type="clause", count=1, names=("indemnification",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.count = 2
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd scripts && python -m pytest charter_eval/tests/test_models.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'charter_eval'`.

- [ ] **Step 3: Write the implementation**

```python
# scripts/charter_eval/__init__.py
# ABOUTME: Evaluation harness for authored charter specs. Runs the production dry-run
# ABOUTME: path, which writes nothing, and scores the result. Not imported by services.
```

```python
# scripts/charter_eval/models.py
# ABOUTME: The harness/metrics data contract. Frozen so metric functions cannot mutate
# ABOUTME: collected results, and JSON-round-trippable so collection and scoring can run
# ABOUTME: at different times (collection needs a live LLM; scoring does not).
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class TypeResult:
    type: str
    count: int
    names: tuple[str, ...]


@dataclass(frozen=True)
class DocResult:
    doc_id: str
    instrument: str
    executed: bool
    variant: str
    repeat: int
    primary_domain: str
    run_general: bool
    specs_applied: tuple[str, ...]
    latency_s: float
    types: tuple[TypeResult, ...]

    @classmethod
    def from_response(cls, doc_id, instrument, executed, variant, repeat,
                      latency_s, payload: dict) -> "DocResult":
        types = tuple(
            TypeResult(type=t["type"], count=t["count"], names=tuple(t.get("names") or ()))
            for t in payload.get("entity_types", [])
        )
        return cls(
            doc_id=doc_id, instrument=instrument, executed=executed,
            variant=variant, repeat=repeat,
            primary_domain=payload.get("primary_domain", ""),
            run_general=bool(payload.get("run_general")),
            specs_applied=tuple(payload.get("specs_applied") or ()),
            latency_s=latency_s, types=types,
        )

    def names_for(self, type_: str) -> tuple[str, ...]:
        for t in self.types:
            if t.type == type_:
                return t.names
        return ()

    def fired_types(self) -> frozenset[str]:
        return frozenset(t.type for t in self.types if t.count > 0)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DocResult":
        return cls(
            **{**d,
               "specs_applied": tuple(d["specs_applied"]),
               "types": tuple(TypeResult(type=t["type"], count=t["count"],
                                         names=tuple(t["names"])) for t in d["types"])},
        )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd scripts && python -m pytest charter_eval/tests/test_models.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/charter_eval/__init__.py scripts/charter_eval/models.py \
        scripts/charter_eval/tests/test_models.py
git commit -m "feat(charter-eval): add harness data contract"
```

---

### Task 3: Metrics M1–M5

The decision hinges on M1 and M2, so they are tested against hand-computed fixtures rather than golden output.

**Files:**
- Create: `scripts/charter_eval/metrics.py`
- Test: `scripts/charter_eval/tests/test_metrics.py`

**Interfaces:**
- Consumes: `DocResult` from Task 2.
- Produces:
  - `mergeability(docs, type_) -> float` — M1. Distinct names of `type_` appearing in ≥2 **distinct `doc_id`s**, over all distinct names of `type_`. Returns `0.0` when there are no names.
  - `median_name_words(docs, type_) -> float` — M2. Median word count over **distinct** names.
  - `volume_per_doc(docs, type_) -> float` — M3. Mean count per distinct `doc_id`.
  - `type_stability(docs, doc_id) -> float` — M4. Mean pairwise Jaccard of `fired_types()` across repeats of one document. `1.0` when fewer than 2 repeats.
  - `count_cv(docs, doc_id, type_) -> float` — M5. Population-stddev / mean of counts across repeats. `0.0` when mean is 0 or repeats < 2.
  - All take `docs: Sequence[DocResult]` and must be called with a single variant's results; `filter_variant(docs, variant)` is provided.

- [ ] **Step 1: Write the failing tests**

```python
# scripts/charter_eval/tests/test_metrics.py
# ABOUTME: M1-M5 against hand-computed fixtures. M1 is the metric the A/B decision turns
# ABOUTME: on, so its edge cases (single doc, repeats of one doc) are pinned explicitly.
import pytest
from charter_eval.models import DocResult, TypeResult
from charter_eval import metrics


def doc(doc_id, variant="B", repeat=0, **types):
    return DocResult(
        doc_id=doc_id, instrument="lease", executed=True, variant=variant,
        repeat=repeat, primary_domain="business/legal-compliance/contracts",
        run_general=False, specs_applied=("business/legal-compliance/contracts",),
        latency_s=10.0,
        types=tuple(TypeResult(type=t, count=len(v), names=tuple(v))
                    for t, v in types.items()),
    )


# --- M1 mergeability -------------------------------------------------------

def test_mergeability_counts_names_shared_by_two_documents():
    docs = [
        doc("a", obligation=["tenant — pay rent", "tenant — insure"]),
        doc("b", obligation=["tenant — pay rent", "landlord — repair"]),
    ]
    # distinct: pay rent, insure, landlord repair = 3; shared by 2+ docs: pay rent = 1
    assert metrics.mergeability(docs, "obligation") == pytest.approx(1 / 3)


def test_mergeability_ignores_repeats_of_the_same_document():
    # The SAME doc_id run twice must not make a name look mergeable.
    docs = [
        doc("a", repeat=0, obligation=["tenant — pay rent"]),
        doc("a", repeat=1, obligation=["tenant — pay rent"]),
    ]
    assert metrics.mergeability(docs, "obligation") == 0.0


def test_mergeability_of_a_span_type_is_zero():
    docs = [
        doc("a", obligation=["tenant may renew this lease for five additional terms"]),
        doc("b", obligation=["if payment is not postmarked by the tenth day"]),
    ]
    assert metrics.mergeability(docs, "obligation") == 0.0


def test_mergeability_of_a_recurring_type_is_one():
    docs = [doc("a", clause=["indemnification"]), doc("b", clause=["indemnification"])]
    assert metrics.mergeability(docs, "clause") == 1.0


def test_mergeability_with_no_names_is_zero_not_an_error():
    assert metrics.mergeability([doc("a", clause=["x"])], "governing_law") == 0.0


# --- M2 name length --------------------------------------------------------

def test_median_name_words_uses_distinct_names():
    docs = [doc("a", obligation=["tenant — pay rent", "tenant — pay rent", "a b c d e f g"])]
    # distinct = ["tenant — pay rent" (4 words), "a b c d e f g" (7 words)] -> median 5.5
    assert metrics.median_name_words(docs, "obligation") == pytest.approx(5.5)


def test_median_name_words_of_absent_type_is_zero():
    assert metrics.median_name_words([doc("a", clause=["x"])], "obligation") == 0.0


# --- M3 volume -------------------------------------------------------------

def test_volume_per_doc_averages_over_distinct_documents():
    docs = [
        doc("a", repeat=0, clause=["x", "y"]),
        doc("a", repeat=1, clause=["x", "y", "z"]),   # same doc, 2 repeats -> mean 2.5
        doc("b", repeat=0, clause=["x"]),             # -> 1.0
    ]
    assert metrics.volume_per_doc(docs, "clause") == pytest.approx((2.5 + 1.0) / 2)


# --- M4 type stability ----------------------------------------------------

def test_type_stability_is_one_when_the_same_types_fire():
    docs = [doc("a", repeat=r, clause=["x"], obligation=["y"]) for r in (0, 1, 2)]
    assert metrics.type_stability(docs, "a") == 1.0


def test_type_stability_drops_when_a_type_goes_missing():
    docs = [
        doc("a", repeat=0, clause=["x"], obligation=["y"]),
        doc("a", repeat=1, clause=["x"]),
    ]
    # Jaccard({clause,obligation},{clause}) = 1/2
    assert metrics.type_stability(docs, "a") == pytest.approx(0.5)


def test_type_stability_of_a_single_run_is_one():
    assert metrics.type_stability([doc("a", clause=["x"])], "a") == 1.0


# --- M5 count variance ----------------------------------------------------

def test_count_cv_is_zero_for_identical_counts():
    docs = [doc("a", repeat=r, clause=["x", "y"]) for r in (0, 1)]
    assert metrics.count_cv(docs, "a", "clause") == 0.0


def test_count_cv_matches_hand_computation():
    docs = [
        doc("a", repeat=0, clause=["x"] * 15),
        doc("a", repeat=1, clause=["x"] * 17),
        doc("a", repeat=2, clause=["x"] * 19),
    ]
    # mean 17, population stddev = sqrt(8/3) ~= 1.63299 -> cv ~= 0.09606
    assert metrics.count_cv(docs, "a", "clause") == pytest.approx(0.09606, abs=1e-4)


def test_count_cv_of_absent_type_is_zero():
    docs = [doc("a", repeat=r, clause=["x"]) for r in (0, 1)]
    assert metrics.count_cv(docs, "a", "obligation") == 0.0


# --- filtering ------------------------------------------------------------

def test_filter_variant_selects_one_arm():
    docs = [doc("a", variant="A", clause=["x"]), doc("a", variant="B", clause=["y"])]
    assert [d.variant for d in metrics.filter_variant(docs, "B")] == ["B"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd scripts && python -m pytest charter_eval/tests/test_metrics.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'charter_eval.metrics'`.

- [ ] **Step 3: Write the implementation**

```python
# scripts/charter_eval/metrics.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd scripts && python -m pytest charter_eval/tests/test_metrics.py -v
```

Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/charter_eval/metrics.py scripts/charter_eval/tests/test_metrics.py
git commit -m "feat(charter-eval): add M1-M5 metric functions"
```

---

### Task 4: Collection harness with injected transport

**Files:**
- Create: `scripts/charter_eval/harness.py`
- Create: `scripts/charter_eval/corpus.example.json`
- Test: `scripts/charter_eval/tests/test_harness.py`

**Interfaces:**
- Consumes: `DocResult.from_response` (Task 2).
- Produces:
  - `Manifest.load(path) -> Manifest` with `Manifest.entries: tuple[CorpusEntry, ...]`; `CorpusEntry(doc_id, path, instrument, executed)`.
  - `collect(manifest, variant, repeats, transport) -> list[DocResult]`.
  - `transport(file_path: str) -> tuple[dict, float]` — returns `(payload, latency_s)`. `HttpTransport(base_url)` is the real one; tests inject a fake.
  - `save(docs, path)` / `load(path) -> list[DocResult]` — JSON lines.

- [ ] **Step 1: Write the failing test**

```python
# scripts/charter_eval/tests/test_harness.py
# ABOUTME: Harness tests with a fake transport. No live LLM in pytest, ever.
import json
import pytest
from charter_eval import harness

MANIFEST = {
    "documents": [
        {"doc_id": "lease-01", "path": "/tmp/lease-01.txt", "instrument": "lease", "executed": True},
        {"doc_id": "nda-01", "path": "/tmp/nda-01.txt", "instrument": "nda", "executed": True},
    ]
}


def _payload(names):
    return {
        "primary_domain": "business/legal-compliance/contracts",
        "secondary_domains": [], "confidence": 0.97,
        "run_general": False,
        "specs_applied": ["business/legal-compliance/contracts"],
        "entity_types": [{"type": "obligation", "count": len(names),
                          "examples": names[:3], "names": names}],
    }


def test_manifest_load(tmp_path):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(MANIFEST))
    m = harness.Manifest.load(str(p))
    assert [e.doc_id for e in m.entries] == ["lease-01", "nda-01"]
    assert m.entries[0].instrument == "lease"
    assert m.entries[0].executed is True


def test_collect_calls_transport_once_per_doc_per_repeat(tmp_path):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(MANIFEST))
    calls = []

    def fake(file_path):
        calls.append(file_path)
        return _payload(["tenant — pay rent"]), 1.5

    docs = harness.collect(harness.Manifest.load(str(p)), "B", repeats=3, transport=fake)
    assert len(calls) == 6, "2 documents x 3 repeats"
    assert len(docs) == 6
    assert sorted({d.repeat for d in docs}) == [0, 1, 2]
    assert {d.variant for d in docs} == {"B"}
    assert docs[0].latency_s == 1.5
    assert docs[0].instrument == "lease"


def test_collect_records_the_failure_and_continues(tmp_path):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(MANIFEST))

    def flaky(file_path):
        if "nda" in file_path:
            raise RuntimeError("422 unsupported")
        return _payload(["tenant — pay rent"]), 1.0

    docs, errors = harness.collect_with_errors(
        harness.Manifest.load(str(p)), "B", repeats=1, transport=flaky)
    assert len(docs) == 1
    assert len(errors) == 1
    assert errors[0]["doc_id"] == "nda-01"
    assert "422" in errors[0]["error"]


def test_save_load_round_trip(tmp_path):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(MANIFEST))
    docs = harness.collect(harness.Manifest.load(str(p)), "B", repeats=1,
                           transport=lambda f: (_payload(["a b"]), 1.0))
    out = tmp_path / "results.jsonl"
    harness.save(docs, str(out))
    assert harness.load(str(out)) == docs


def test_http_transport_builds_the_dry_run_url():
    t = harness.HttpTransport("http://localhost:8000")
    assert t.url == "http://localhost:8000/ingest?dry_run=true&full_names=true"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd scripts && python -m pytest charter_eval/tests/test_harness.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'charter_eval.harness'`.

- [ ] **Step 3: Write the implementation**

```python
# scripts/charter_eval/harness.py
# ABOUTME: Collects dry-run results for one variant. dry_run=true writes nothing to the
# ABOUTME: graph, so this runs the production path safely; transport is injected so the
# ABOUTME: tests never make a live LLM call.
import json
import time
from dataclasses import dataclass
from collections.abc import Callable, Sequence

from .models import DocResult

Transport = Callable[[str], tuple[dict, float]]


@dataclass(frozen=True)
class CorpusEntry:
    doc_id: str
    path: str
    instrument: str
    executed: bool


@dataclass(frozen=True)
class Manifest:
    entries: tuple[CorpusEntry, ...]

    @classmethod
    def load(cls, path: str) -> "Manifest":
        with open(path) as f:
            raw = json.load(f)
        return cls(entries=tuple(
            CorpusEntry(doc_id=d["doc_id"], path=d["path"],
                        instrument=d["instrument"], executed=bool(d["executed"]))
            for d in raw["documents"]))


class HttpTransport:
    """The real transport. `full_names=true` is required — see Task 1."""

    def __init__(self, base_url: str, timeout: float = 900.0):
        self.url = f"{base_url.rstrip('/')}/ingest?dry_run=true&full_names=true"
        self.timeout = timeout

    def __call__(self, file_path: str) -> tuple[dict, float]:
        import httpx
        started = time.monotonic()
        with open(file_path, "rb") as f:
            r = httpx.post(self.url, files={"file": (file_path.split("/")[-1], f)},
                           timeout=self.timeout)
        elapsed = time.monotonic() - started
        r.raise_for_status()
        return r.json(), elapsed


def collect_with_errors(manifest: Manifest, variant: str, repeats: int,
                        transport: Transport) -> tuple[list[DocResult], list[dict]]:
    docs: list[DocResult] = []
    errors: list[dict] = []
    for repeat in range(repeats):
        for entry in manifest.entries:
            try:
                payload, latency = transport(entry.path)
            except Exception as e:            # one bad document must not lose the run
                errors.append({"doc_id": entry.doc_id, "repeat": repeat, "error": str(e)})
                continue
            docs.append(DocResult.from_response(
                entry.doc_id, entry.instrument, entry.executed,
                variant, repeat, latency, payload))
    return docs, errors


def collect(manifest: Manifest, variant: str, repeats: int,
            transport: Transport) -> list[DocResult]:
    docs, _ = collect_with_errors(manifest, variant, repeats, transport)
    return docs


def save(docs: Sequence[DocResult], path: str) -> None:
    with open(path, "w") as f:
        for d in docs:
            f.write(json.dumps(d.to_dict()) + "\n")


def load(path: str) -> list[DocResult]:
    with open(path) as f:
        return [DocResult.from_dict(json.loads(line)) for line in f if line.strip()]
```

```json
// scripts/charter_eval/corpus.example.json
{
  "_comment": "Copy to corpus.json and point paths at your DS-scratch corpus dir. Never commit real contracts.",
  "documents": [
    {"doc_id": "lease-01",    "path": "/home/yi/Downloads/lease.txt",              "instrument": "lease",   "executed": true},
    {"doc_id": "sublease-01", "path": "/home/yi/Downloads/sublease-agreement.docx", "instrument": "sublease", "executed": false}
  ]
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd scripts && python -m pytest charter_eval/tests/test_harness.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Verify the dry-run really writes nothing (once, by hand)**

```bash
DB=$(ls -t ~/orrery-data/workspaces/*/orrery.db | head -1)
BEFORE=$(python3 -c "import sqlite3;print(sqlite3.connect('$DB').execute('SELECT count(*) FROM entities').fetchone()[0])")
curl -s -o /dev/null -X POST "http://localhost:8000/ingest?dry_run=true&full_names=true" \
  -F "file=@/home/yi/Downloads/sublease-agreement.docx"
AFTER=$(python3 -c "import sqlite3;print(sqlite3.connect('$DB').execute('SELECT count(*) FROM entities').fetchone()[0])")
echo "entities before=$BEFORE after=$AFTER"; [ "$BEFORE" = "$AFTER" ] && echo OK || echo "LEAK"
```

Expected: `OK`. Note the workspace DB is under `~/orrery-data/workspaces/<id>/`, **not** the top-level `orrery.db` — querying the wrong file returns empty results rather than an error.

- [ ] **Step 6: Commit**

```bash
git add scripts/charter_eval/harness.py scripts/charter_eval/corpus.example.json \
        scripts/charter_eval/tests/test_harness.py
git commit -m "feat(charter-eval): add collection harness with injected transport"
```

---

### Task 5: The frozen decision rule

Isolated in its own module so the pre-registered thresholds live in exactly one place and any change to them shows up as a reviewable diff.

**Files:**
- Create: `scripts/charter_eval/report.py`
- Test: `scripts/charter_eval/tests/test_report.py`

**Interfaces:**
- Consumes: `metrics` (Task 3), `DocResult` (Task 2).
- Produces: `THRESHOLDS = {"m1_min": 0.30, "m2_max_words": 6.0, "m6_min": 0.80}`; `decide(docs_b, precision_b) -> Decision`; `Decision(ship: str, m1: float, m2: float, m6: float, reasons: tuple[str, ...])`; `render_table(docs, types) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# scripts/charter_eval/tests/test_report.py
# ABOUTME: The pre-registered A/B rule. These thresholds are frozen by the design doc;
# ABOUTME: a diff here is a deliberate protocol change, not a tweak.
import pytest
from charter_eval.models import DocResult, TypeResult
from charter_eval import report


def doc(doc_id, names, variant="B"):
    return DocResult(
        doc_id=doc_id, instrument="lease", executed=True, variant=variant, repeat=0,
        primary_domain="business/legal-compliance/contracts", run_general=False,
        specs_applied=("business/legal-compliance/contracts",), latency_s=10.0,
        types=(TypeResult(type="obligation", count=len(names), names=tuple(names)),))


def test_thresholds_are_the_pre_registered_values():
    assert report.THRESHOLDS == {"m1_min": 0.30, "m2_max_words": 6.0, "m6_min": 0.80}


def test_ships_b_when_all_three_pass():
    docs = [doc("a", ["tenant — pay rent", "tenant — insure"]),
            doc("b", ["tenant — pay rent", "tenant — insure"])]
    d = report.decide(docs, precision_b=0.9)
    assert d.ship == "B"
    assert d.m1 == pytest.approx(1.0)
    # distinct names are 3 words ("tenant — insure") and 4 words ("tenant — pay rent")
    assert d.m2 == pytest.approx(3.5)


def test_ships_a_when_mergeability_is_too_low():
    docs = [doc("a", ["tenant — pay rent"]), doc("b", ["landlord — repair roof"])]
    d = report.decide(docs, precision_b=0.9)
    assert d.ship == "A"
    assert any("m1" in r for r in d.reasons)


def test_ships_a_when_names_are_too_long():
    long_a = "tenant may renew this lease for five additional successive one-year terms"
    docs = [doc("a", [long_a]), doc("b", [long_a])]
    d = report.decide(docs, precision_b=0.95)
    assert d.ship == "A"
    assert any("m2" in r for r in d.reasons)


def test_ships_a_when_precision_collapses():
    docs = [doc("a", ["tenant — pay rent"]), doc("b", ["tenant — pay rent"])]
    d = report.decide(docs, precision_b=0.5)
    assert d.ship == "A"
    assert any("m6" in r for r in d.reasons)


def test_reasons_list_every_failure_not_just_the_first():
    long_a = "tenant may renew this lease for five additional successive one-year terms"
    docs = [doc("a", [long_a]), doc("b", ["landlord — repair roof"])]
    d = report.decide(docs, precision_b=0.1)
    assert len(d.reasons) == 3


def test_boundary_values_pass():
    """m1 exactly 0.30, m2 exactly 6.0, m6 exactly 0.80 must all PASS (>=, <=, >=)."""
    shared = [f"s{i} b c d e f" for i in range(3)]      # 6 words each, in BOTH docs
    unique = [f"u{i} b c d e f" for i in range(7)]      # 6 words each, only in doc a
    docs = [doc("a", shared + unique), doc("b", shared)]
    d = report.decide(docs, precision_b=0.80)
    assert d.m1 == pytest.approx(0.30), "3 shared of 10 distinct"
    assert d.m2 == pytest.approx(6.0)
    assert d.ship == "B", "thresholds are inclusive; boundary must not fail"
    assert d.reasons == ()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd scripts && python -m pytest charter_eval/tests/test_report.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'charter_eval.report'`.

- [ ] **Step 3: Write the implementation**

```python
# scripts/charter_eval/report.py
# ABOUTME: The pre-registered A/B decision rule and the report table. Thresholds are
# ABOUTME: frozen by docs/superpowers/specs/2026-08-21-contracts-charter-evaluation-design.md
# ABOUTME: — they are stated before the run precisely so they cannot be moved after it.
from dataclasses import dataclass
from collections.abc import Sequence

from . import metrics
from .models import DocResult

THRESHOLDS = {"m1_min": 0.30, "m2_max_words": 6.0, "m6_min": 0.80}

DECISION_TYPE = "obligation"


@dataclass(frozen=True)
class Decision:
    ship: str
    m1: float
    m2: float
    m6: float
    reasons: tuple[str, ...]


def decide(docs_b: Sequence[DocResult], precision_b: float) -> Decision:
    """Ship B iff obligation M1 >= 0.30 AND M2 <= 6 words AND M6 >= 0.80."""
    m1 = metrics.mergeability(docs_b, DECISION_TYPE)
    m2 = metrics.median_name_words(docs_b, DECISION_TYPE)
    reasons: list[str] = []
    if m1 < THRESHOLDS["m1_min"]:
        reasons.append(f"m1 mergeability {m1:.2f} < {THRESHOLDS['m1_min']}")
    if m2 > THRESHOLDS["m2_max_words"]:
        reasons.append(f"m2 median name words {m2:.1f} > {THRESHOLDS['m2_max_words']}")
    if precision_b < THRESHOLDS["m6_min"]:
        reasons.append(f"m6 precision {precision_b:.2f} < {THRESHOLDS['m6_min']}")
    return Decision(ship="B" if not reasons else "A",
                    m1=m1, m2=m2, m6=precision_b, reasons=tuple(reasons))


def render_table(docs: Sequence[DocResult], types: Sequence[str]) -> str:
    header = f"{'type':<20}{'M1 merge':>10}{'M2 words':>10}{'M3 /doc':>10}"
    lines = [header, "-" * len(header)]
    for t in types:
        lines.append(f"{t:<20}"
                     f"{metrics.mergeability(docs, t):>10.2f}"
                     f"{metrics.median_name_words(docs, t):>10.1f}"
                     f"{metrics.volume_per_doc(docs, t):>10.1f}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd scripts && python -m pytest charter_eval/tests/test_report.py -v
```

Expected: 7 passed. `test_boundary_values_pass` pins the inclusive boundary exactly (m1 = 0.30, m2 = 6.0, m6 = 0.80 all ship B). If it fails, the comparison operators are wrong — fix those, and do **not** relax `THRESHOLDS`.

- [ ] **Step 5: Commit**

```bash
git add scripts/charter_eval/report.py scripts/charter_eval/tests/test_report.py
git commit -m "feat(charter-eval): add frozen A/B decision rule"
```

---

### Task 6: Precision sampler (M6) and CLI

**Files:**
- Create: `scripts/charter_eval/sample.py`
- Create: `scripts/charter_eval/__main__.py`
- Test: `scripts/charter_eval/tests/test_sample.py`

**Interfaces:**
- Consumes: `DocResult` (Task 2), `harness.load` (Task 4), `report.decide`/`render_table` (Task 5).
- Produces:
  - `stratified_sample(docs, per_type, seed) -> list[dict]` — rows `{doc_id, type, name, correct}` with `correct` blank for hand-labelling. Deterministic for a given seed.
  - `precision_from_csv(path, type_=None) -> float` — reads back labels; `correct` in `{y,n}`.
  - CLI: `python -m charter_eval collect --manifest M --variant B --repeats 3 --out R.jsonl`, `... report --results R.jsonl [--precision-csv P.csv]`, `... sample --results R.jsonl --out P.csv --per-type 10`.

- [ ] **Step 1: Write the failing test**

```python
# scripts/charter_eval/tests/test_sample.py
# ABOUTME: M6 needs hand-labelling, so the sampler must be deterministic (a re-run must
# ABOUTME: not invalidate labels already applied) and must read its own CSV back.
import csv
from charter_eval.models import DocResult, TypeResult
from charter_eval import sample


def doc(doc_id, **types):
    return DocResult(
        doc_id=doc_id, instrument="lease", executed=True, variant="B", repeat=0,
        primary_domain="business/legal-compliance/contracts", run_general=False,
        specs_applied=("business/legal-compliance/contracts",), latency_s=1.0,
        types=tuple(TypeResult(type=t, count=len(v), names=tuple(v)) for t, v in types.items()))


DOCS = [doc("a", obligation=[f"o{i}" for i in range(20)], clause=["c1", "c2"])]


def test_stratified_sample_caps_per_type():
    rows = sample.stratified_sample(DOCS, per_type=5, seed=42)
    by_type = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    assert len(by_type["obligation"]) == 5
    assert len(by_type["clause"]) == 2, "fewer than per_type available -> take all"
    assert all(r["correct"] == "" for r in rows)


def test_stratified_sample_is_deterministic():
    a = sample.stratified_sample(DOCS, per_type=5, seed=42)
    b = sample.stratified_sample(DOCS, per_type=5, seed=42)
    assert a == b


def test_precision_from_csv(tmp_path):
    p = tmp_path / "labels.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "type", "name", "correct"])
        w.writeheader()
        for name, correct in [("o1", "y"), ("o2", "y"), ("o3", "n"), ("o4", "y")]:
            w.writerow({"doc_id": "a", "type": "obligation", "name": name, "correct": correct})
        w.writerow({"doc_id": "a", "type": "clause", "name": "c1", "correct": "n"})
    assert sample.precision_from_csv(str(p), "obligation") == 0.75
    assert sample.precision_from_csv(str(p)) == 0.6


def test_unlabelled_rows_are_excluded(tmp_path):
    p = tmp_path / "labels.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "type", "name", "correct"])
        w.writeheader()
        w.writerow({"doc_id": "a", "type": "obligation", "name": "o1", "correct": "y"})
        w.writerow({"doc_id": "a", "type": "obligation", "name": "o2", "correct": ""})
    assert sample.precision_from_csv(str(p), "obligation") == 1.0
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd scripts && python -m pytest charter_eval/tests/test_sample.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'charter_eval.sample'`.

- [ ] **Step 3: Write the sampler**

```python
# scripts/charter_eval/sample.py
# ABOUTME: Stratified sampling for M6 precision, which only a human can measure. Seeded
# ABOUTME: so re-running does not invalidate labels already applied to a previous sample.
import csv
import random
from collections import defaultdict
from collections.abc import Sequence

from .models import DocResult

FIELDNAMES = ["doc_id", "type", "name", "correct"]


def stratified_sample(docs: Sequence[DocResult], per_type: int, seed: int = 42) -> list[dict]:
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
```

- [ ] **Step 4: Write the CLI**

```python
# scripts/charter_eval/__main__.py
# ABOUTME: CLI for the charter evaluation: collect (live, slow), sample (for labelling),
# ABOUTME: report (pure). Collection and scoring are separate commands on purpose.
import argparse
import sys

from . import harness, report, sample

DECL_TYPES = ["party", "signatory", "organization", "clause", "obligation",
              "condition_trigger", "monetary_term", "term_period", "governing_law",
              "subject_property", "location", "document", "date_ref"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="charter_eval")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect")
    c.add_argument("--manifest", required=True)
    c.add_argument("--variant", required=True, choices=["v1", "A", "B"])
    c.add_argument("--repeats", type=int, default=3)
    c.add_argument("--base-url", default="http://localhost:8000")
    c.add_argument("--out", required=True)

    r = sub.add_parser("report")
    r.add_argument("--results", required=True)
    r.add_argument("--precision-csv")

    s = sub.add_parser("sample")
    s.add_argument("--results", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--per-type", type=int, default=10)
    s.add_argument("--seed", type=int, default=42)

    a = p.parse_args(argv)

    if a.cmd == "collect":
        m = harness.Manifest.load(a.manifest)
        docs, errors = harness.collect_with_errors(
            m, a.variant, a.repeats, harness.HttpTransport(a.base_url))
        harness.save(docs, a.out)
        print(f"collected {len(docs)} results -> {a.out}")
        for e in errors:
            print(f"  ERROR {e['doc_id']} repeat={e['repeat']}: {e['error']}", file=sys.stderr)
        return 0

    if a.cmd == "sample":
        sample.write_csv(
            sample.stratified_sample(harness.load(a.results), a.per_type, a.seed), a.out)
        print(f"wrote sample -> {a.out}  (label the `correct` column y/n)")
        return 0

    docs = harness.load(a.results)
    print(report.render_table(docs, DECL_TYPES))
    print()
    if a.precision_csv:
        prec = sample.precision_from_csv(a.precision_csv, report.DECISION_TYPE)
        d = report.decide(docs, prec)
        print(f"SHIP {d.ship}   m1={d.m1:.2f} m2={d.m2:.1f} m6={d.m6:.2f}")
        for reason in d.reasons:
            print(f"  fail: {reason}")
    else:
        print("no --precision-csv: M6 unmeasured, decision withheld")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd scripts && python -m pytest charter_eval/ -v
```

Expected: all tests pass (32 total across Tasks 2-6).

- [ ] **Step 6: Commit**

```bash
git add scripts/charter_eval/sample.py scripts/charter_eval/__main__.py \
        scripts/charter_eval/tests/test_sample.py
git commit -m "feat(charter-eval): add precision sampler and CLI"
```

---

### Task 7: Write the two variant specs

Both must be **complete and self-contained** — an authored spec replaces the general pass, so anything omitted is not extracted at all. Both start from the shipped v1 (`GET /charter?domain=business%2Flegal-compliance%2Fcontracts`).

**Files:**
- Create: `orchestrator/specs/contracts_charter_v2a.md`
- Create: `orchestrator/specs/contracts_charter_v2b.md`

**Interfaces:**
- Consumes: v1 spec text, retrieved from the live charter.
- Produces: two spec files, POSTable as `{"domain","aliases","spec"}` to `/charter`.

- [ ] **Step 1: Export v1 as the common base**

```bash
mkdir -p /tmp/charter && curl -s \
  "http://localhost:8000/charter?domain=business%2Flegal-compliance%2Fcontracts" \
  | python3 -c "import json,sys; sys.stdout.write(json.load(sys.stdin)['spec'])" \
  > /tmp/charter/v1.md
wc -l /tmp/charter/v1.md   # expect 267
```

- [ ] **Step 2: Build variant A — delete the two span types**

```bash
cp /tmp/charter/v1.md orchestrator/specs/contracts_charter_v2a.md
```

Then edit `contracts_charter_v2a.md` by hand, making exactly these changes:

1. In the **Entity Types** table, delete the `obligation` and `condition_trigger` rows.
2. In **Types deliberately excluded**, add:
   `- \`obligation\` and \`condition_trigger\` — provision-level spans, not recurring entities. Measured at 228 and 81 instances on one commercial lease, with sentence-length unique names that never merge across documents. Capture the provision as \`clause\` instead.`
3. In the **Type Decision Tree**, delete steps 2 and 3 and renumber the remainder 1-4.
4. In **What to Extract**, delete condition 3 ("It states a duty, a right, or a contingency").
5. In **Entity Boundary Guidance**, delete the `obligation` block.
6. In **Entity Naming Rules**, delete rules 3 and 4 and renumber.
7. In the **Worked Example**, remove every `obligation` and `condition_trigger` entity from the JSON and from both tables. Expected remaining: 6 entities.
8. Change the type count in the Output Schema from `13` to `11`.
9. In **Execution Notes**, replace the "Recall over precision on `clause` and `obligation`" bullet with one naming `clause` only.

- [ ] **Step 3: Build variant B — constrain obligation naming**

```bash
cp /tmp/charter/v1.md orchestrator/specs/contracts_charter_v2b.md
```

Then edit `contracts_charter_v2b.md`, making exactly these changes:

1. Replace the `obligation` row in the **Entity Types** table with:

```markdown
| `obligation` | A duty, named as `<party> — <duty>` in **six words or fewer** | "tenant — pay monthly rent", "tenant — maintain insurance", "sublessor — provide inventory form" |
```

2. Replace the `condition_trigger` row with:

```markdown
| `condition_trigger` | A contingency, named as a short noun phrase in **six words or fewer** | "nonpayment of rent", "premises returned in same condition", "landlord consent withheld" |
```

3. Replace **Entity Naming Rules** items 3 and 4 with:

```markdown
3. **`obligation`: `<party> — <duty>`, six words or fewer.** The party is the role, not the
   name. The duty is a bare verb phrase in the infinitive. Drop every qualifier, amount,
   deadline, and carve-out — those are already captured by `monetary_term`, `term_period`,
   and `condition_trigger`, and repeating them here produces a name unique to one document
   that can never merge with anything.

   - ✅ `"tenant — pay monthly rent"`
   - ❌ `"tenant may renew this lease for five additional successive one-year terms at a monthly rent of $100,000 per month"`
   - ✅ `"tenant — renew lease"`
   - ✅ `"tenant — surrender premises"`
   - ❌ `"subtenant agrees to surrender and deliver to the sublessor the premises and all furniture and decorations in as good a condition as they were at the beginning of the term"`

   **The point of the limit is mergeability.** The same duty appears in thousands of
   contracts; named this way it becomes one graph node with thousands of sources. Named as
   a sentence it becomes thousands of orphan nodes.

4. **`condition_trigger`: a short noun phrase, six words or fewer.** Name the *condition*,
   not the sentence that states it. Drop the "if"/"unless" — the type already means
   "contingency".

   - ✅ `"nonpayment of rent"`
   - ❌ `"if payment is not postmarked or received by landlord on or before the tenth day of each month"`
   - ✅ `"premises destroyed by casualty"`
   - ✅ `"subtenant under 18"`
```

4. In **Entity Boundary Guidance**, replace the `obligation` block with:

```markdown
**`obligation` — one duty per entity, named `<party> — <duty>` in six words or fewer.**
A paragraph stating three duties yields three obligations, each short.

- ✅ `"subtenant — surrender premises"` and `"subtenant — pay damages"` — two entities
- ❌ one entity carrying the whole paragraph
```

5. In the **Worked Example**, rewrite every `obligation` and `condition_trigger` name to the new form. Expected result:

```json
{"name": "subtenant — pay utilities", "type": "obligation"},
{"name": "subtenant — pay deposit", "type": "obligation"},
{"name": "sublessor — refund deposit", "type": "obligation"},
{"name": "premises returned in same condition", "type": "condition_trigger"}
```

6. In **Execution Notes**, add:
   `- **The six-word limit on \`obligation\` and \`condition_trigger\` is load-bearing.** It exists so those nodes merge across documents. Relaxing it reintroduces the v1 failure: 228 orphan nodes from a single lease.`

- [ ] **Step 4: Verify both are self-contained**

```bash
for f in orchestrator/specs/contracts_charter_v2a.md orchestrator/specs/contracts_charter_v2b.md; do
  echo "== $f"
  for s in "Entity Types" "Extraction Rules" "Entity Naming Rules" "Output Schema" "Worked Example"; do
    grep -q "$s" "$f" && echo "  ok: $s" || echo "  MISSING: $s"
  done
done
grep -c "obligation" orchestrator/specs/contracts_charter_v2a.md   # expect 1 (the exclusion note)
grep -c "six words or fewer" orchestrator/specs/contracts_charter_v2b.md  # expect >= 4
```

Expected: every section present in both; the counts as annotated.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/specs/contracts_charter_v2a.md orchestrator/specs/contracts_charter_v2b.md
git commit -m "feat(specs): add contracts charter variants A and B for evaluation"
```

---

### Task 8: Assemble the corpus

The two documents on hand **cannot** answer the question: M1 needs the same instrument type across multiple documents, and one executed lease plus one blank sublease template gives no measurable overlap.

**Files:**
- Create: `scripts/charter_eval/corpus.json` (gitignored — verify it is not committed)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `Manifest.load` schema (Task 4).
- Produces: a manifest with ≥10 documents meeting the spec's diversity table.

- [ ] **Step 1: Confirm the manifest cannot be committed**

```bash
grep -q '^scripts/charter_eval/corpus.json$' .gitignore \
  || echo 'scripts/charter_eval/corpus.json' >> .gitignore
git check-ignore -v scripts/charter_eval/corpus.json || echo "NOT IGNORED — fix before continuing"
```

- [ ] **Step 2: Acquire the corpus**

Source: **SEC EDGAR full-text search**, `EX-10` exhibits (material contracts) — public, free, and already the provenance of `lease.txt`, whose first line is `EX-10 2 elmonteleaseforfiling.htm MATERIAL CONTRACT`.

`https://efts.sec.gov/LATEST/search-index?q=%22<phrase>%22&forms=8-K,10-K,10-Q`

| Instrument | Need | Search phrase | Have |
|---|---|---|---|
| lease (executed) | 3 | `"COMMERCIAL LEASE AGREEMENT"` | 1 (`lease.txt`) |
| sublease (template) | 1 | — | 1 (`sublease-agreement.docx`) |
| NDA | 3 | `"MUTUAL NONDISCLOSURE AGREEMENT"` | 0 |
| MSA / SOW | 2 | `"MASTER SERVICES AGREEMENT"` | 0 |
| amendment | 1 | `"FIRST AMENDMENT TO LEASE"` | 0 |

Save to a DS-scratch directory, not this repo. Keep each as `.txt` or `.docx` — both are in `ALL_SUPPORTED_EXTENSIONS`.

- [ ] **Step 3: Write the manifest**

```bash
cp scripts/charter_eval/corpus.example.json scripts/charter_eval/corpus.json
```

Edit to list all ~11 documents with correct `instrument` and `executed` values. `instrument` must group same-type documents identically — M1 is computed within the whole corpus but interpreted per instrument, so a typo silently weakens the signal.

- [ ] **Step 4: Verify the manifest loads and every path exists**

```bash
cd scripts && python -c "
from charter_eval.harness import Manifest
import os, collections
m = Manifest.load('charter_eval/corpus.json')
missing = [e.path for e in m.entries if not os.path.exists(e.path)]
print('documents:', len(m.entries))
print('by instrument:', dict(collections.Counter(e.instrument for e in m.entries)))
print('MISSING:', missing or 'none')
assert not missing, 'fix paths before collecting'
assert len(m.entries) >= 10, 'corpus too small for M1'
print('OK')
"
```

Expected: `OK`, ≥3 leases and ≥3 NDAs.

- [ ] **Step 5: Commit the gitignore change only**

```bash
git add .gitignore
git status --short   # confirm corpus.json does NOT appear
git commit -m "chore: ignore charter eval corpus manifest"
```

---

### Task 9: Run the A/B and record the verdict

**Files:**
- Create: `experiments/2026-08-21-contracts-charter-ab/README.md`
- Modify: `experiments/README.md`

**Interfaces:**
- Consumes: the CLI (Task 6), the variant specs (Task 7), the corpus (Task 8).
- Produces: the lab-notebook record and the index row.

- [ ] **Step 1: Collect the v1 baseline**

```bash
cd scripts && python -m charter_eval collect --manifest charter_eval/corpus.json \
  --variant v1 --repeats 3 --out /tmp/charter/v1.jsonl
```

Expected: `collected 33 results`. At ~126s/lease this is roughly 45-70 minutes — run it in the background.

- [ ] **Step 2: POST variant A, collect, then POST variant B and collect**

```bash
ALIASES='["legal/contracts","contracts","legal/agreements","business/legal/contracts","legal-compliance/contracts","business/legal-compliance/agreements","legal/leases","business/legal-compliance/leases"]'
post() {  # $1 = spec file
  python3 -c "
import json,sys
print(json.dumps({'domain':'business/legal-compliance/contracts',
                  'aliases':json.loads('''$ALIASES'''),
                  'spec':open('$1').read()}))" > /tmp/charter/payload.json
  curl -s -X POST http://localhost:8000/charter -H 'Content-Type: application/json' \
    --data-binary @/tmp/charter/payload.json
}

post orchestrator/specs/contracts_charter_v2a.md   # -> spec_version 2
cd scripts && python -m charter_eval collect --manifest charter_eval/corpus.json \
  --variant A --repeats 3 --out /tmp/charter/a.jsonl

post orchestrator/specs/contracts_charter_v2b.md   # -> spec_version 3
cd scripts && python -m charter_eval collect --manifest charter_eval/corpus.json \
  --variant B --repeats 3 --out /tmp/charter/b.jsonl
```

Each POST bumps the version; re-POSTing the winner at the end is therefore safe and is how the final state is set. Confirm `run_general: false` and the right `specs_applied` appear in the collected JSON before trusting a run.

- [ ] **Step 3: Label the precision sample for B**

```bash
cd scripts && python -m charter_eval sample --results /tmp/charter/b.jsonl \
  --out /tmp/charter/b-precision.csv --per-type 10
```

Open the CSV and fill the `correct` column with `y`/`n` by hand. Judge whether the **name is a correct instance of its type** — not whether the extraction is complete. Two known v1 errors to watch for: a role typed as `organization` (`"supervising architect"`), and an insurance requirement typed as `document` (`"fire and extended coverage insurance policies"`).

- [ ] **Step 4: Produce the decision**

```bash
cd scripts
for v in v1 a b; do echo "=== $v ==="; python -m charter_eval report --results /tmp/charter/$v.jsonl; done
echo "=== DECISION ==="
python -m charter_eval report --results /tmp/charter/b.jsonl \
  --precision-csv /tmp/charter/b-precision.csv
```

Expected: a `SHIP A` or `SHIP B` line with the three metric values. If it says `SHIP A`, the reasons list which thresholds failed.

- [ ] **Step 5: POST the winner and verify the final state**

```bash
post orchestrator/specs/contracts_charter_v2<WINNER>.md
curl -s "http://localhost:8000/charter?domain=business%2Flegal-compliance%2Fcontracts" \
  | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('spec_version:', d['spec_version'], ' aliases:', len(d['aliases']))
print('has six-word rule:', 'six words or fewer' in d['spec'])"
```

Expected: the version incremented, 8 aliases intact, and the six-word rule present iff B won.

- [ ] **Step 6: Write the experiment record**

Create `experiments/2026-08-21-contracts-charter-ab/README.md` following the template in `experiments/README.md`, filling in real measured numbers:

```markdown
# Contracts charter — obligation shape A/B
2026-08-21 · Complete, n=<docs>x3 repeats · yi

## Question / hypothesis
The v1 charter emits 228 `obligation` entities from one commercial lease, named as
sentence-length unique strings that can never merge across documents. Is `obligation`
salvageable with a six-word naming rule (B), or must it be dropped (A)?

## Setup
- Base commit: 833eb05
- Arms: v1 (shipped), A (11 types, spans deleted), B (13 types, `<party> — <duty>` ≤6 words)
- Params: domain business/legal-compliance/contracts, <N> documents x 3 repeats,
  EXTRACTION_MODEL=<model>, backend=<backend>
- Artifacts: DS-scratch/<dir>/ (corpus, raw jsonl, precision CSV)

## How to run
    python -m charter_eval collect --manifest corpus.json --variant B --repeats 3 --out b.jsonl
    python -m charter_eval report --results b.jsonl --precision-csv b-precision.csv

## Results
| arm | entities/lease | obligation M1 | obligation M2 | M4 stability | M6 precision | s/doc |
|---|---|---|---|---|---|---|
| v1 | 522 | <> | <> | 1.00 | <> | 126 |
| A  | <> | n/a | n/a | <> | <> | <> |
| B  | <> | <> | <> | <> | <> | <> |

## Conclusion + caveats
<verdict, against the pre-registered rule: m1>=0.30, m2<=6, m6>=0.80>

Caveats: single extraction model; corpus is SEC EX-10 filings, skewed toward
commercial real property; M6 labelled by one person; recall never measured.
```

- [ ] **Step 7: Add the index row**

Insert at the top of the Index table in `experiments/README.md`:

```markdown
| 2026-08-21 | [Contracts charter — obligation shape A/B](./2026-08-21-contracts-charter-ab/) | Complete, n=<N>x3 | <verdict> |
```

- [ ] **Step 8: Commit**

```bash
git add experiments/2026-08-21-contracts-charter-ab/README.md experiments/README.md
git commit -m "docs(experiments): record contracts charter obligation-shape A/B"
```

---

## Self-Review

**1. Spec coverage.** Every design-doc section maps to a task: M1-M5 → Task 3; M6 → Task 6; M7 → captured by `latency_s` in Task 2 and reported in Task 9; corpus requirement → Task 8; pre-registered rule → Task 5 (frozen in `THRESHOLDS`, tested); variants A/B → Task 7; "out of scope: pipeline wiring" → honoured, no task re-tests it; the record → Task 9. The design doc's observation that `examples[:3]` blocks M1 is what Task 1 exists for.

**2. Placeholder scan.** No TBDs. Every code step carries runnable code. The `<WINNER>`, `<N>`, and `<>` markers in Task 9 are result placeholders in a document written *after* measurement, not unspecified work.

**3. Type consistency.** `DocResult`/`TypeResult` field names are identical across Tasks 2-6. `names_for` and `fired_types` are defined in Task 2 and used in Task 3. `Manifest`/`CorpusEntry` defined in Task 4, used in Tasks 6 and 8. `THRESHOLDS` keys (`m1_min`, `m2_max_words`, `m6_min`) match between `report.py` and its test. `report.DECISION_TYPE` is used by the CLI in Task 6. `harness.collect_with_errors` is defined in Task 4 and called in Task 6.

**One risk the plan does not remove.** Task 8 depends on acquiring 9 contracts that do not currently exist locally. Until that corpus exists, M1 is unmeasurable and the A/B question cannot be answered — Tasks 1-7 are all buildable without it, but Task 9 is blocked. If the corpus proves hard to assemble, the fallback is to ship A on the argument already established (span-shaped nodes cannot merge, and the v1 measurement of 228 orphan nodes per lease is direct evidence) and skip the experiment. That is a defensible decision without further measurement; it just forgoes the chance that B rescues the type.
