# ABOUTME: The pre-registered A/B decision rule and the report table. Thresholds are
# ABOUTME: frozen by docs/superpowers/specs/2026-08-21-contracts-charter-evaluation-design.md
# ABOUTME: — they are stated before the run precisely so they cannot be moved after it.
import statistics
from dataclasses import dataclass
from collections.abc import Sequence

from . import metrics
from .models import DocResult

THRESHOLDS = {"m1_min": 0.30, "m2_max_words": 6.0, "m6_min": 0.80}

DECISION_TYPE = "obligation"

INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class Decision:
    ship: str
    m1: float
    m2: float
    m6: float
    reasons: tuple[str, ...]


def _fail(label: str, observed: float, op: str, threshold: float) -> str:
    """One failure reason, observed and threshold at the SAME precision.

    This string is the whole human-readable justification for accepting a pre-registered
    verdict, so it must not read as a contradiction: at :.2f a near-miss printed
    "m1 mergeability 0.30 < 0.3", which invites the operator to distrust the run and
    re-do it. Four decimals show the failure that rounding hid.
    """
    return f"{label} {observed:.4f} {op} {threshold:.4f}"


def decide(docs_b: Sequence[DocResult], precision_b: float) -> Decision:
    """Ship B iff obligation M1 >= 0.30 AND M2 <= 6 words AND M6 >= 0.80.

    A collection that produced no `obligation` names at all yields m1 = m2 = 0.0, which
    would otherwise satisfy the m1/m2 tests and render an entirely-failed run as a
    confident SHIP A. That state is reported as INSUFFICIENT_DATA, not as a verdict.
    """
    if not any(d.names_for(DECISION_TYPE) for d in docs_b):
        return Decision(
            ship=INSUFFICIENT_DATA, m1=0.0, m2=0.0, m6=precision_b,
            reasons=(f"no {DECISION_TYPE} names in the results: the decision rule cannot "
                     f"be evaluated (collection failed, or the results were fetched "
                     f"without full_names=true)",))
    m1 = metrics.mergeability(docs_b, DECISION_TYPE)
    m2 = metrics.median_name_words(docs_b, DECISION_TYPE)
    reasons: list[str] = []
    if m1 < THRESHOLDS["m1_min"]:
        reasons.append(_fail("m1 mergeability", m1, "<", THRESHOLDS["m1_min"]))
    if m2 > THRESHOLDS["m2_max_words"]:
        reasons.append(_fail("m2 median name words", m2, ">", THRESHOLDS["m2_max_words"]))
    if precision_b < THRESHOLDS["m6_min"]:
        reasons.append(_fail("m6 precision", precision_b, "<", THRESHOLDS["m6_min"]))
    return Decision(ship="B" if not reasons else "A",
                    m1=m1, m2=m2, m6=precision_b, reasons=tuple(reasons))


def _mean(values: Sequence[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def render_table(docs: Sequence[DocResult], types: Sequence[str]) -> str:
    """M1/M2/M3/M5 per type, plus M4 for the run.

    M4 and M5 are per-DOCUMENT metrics (they are computed across repeats of one
    document), so both are aggregated here as a mean over the distinct documents in
    `docs` — stated in the header so a reader does not mistake either for a per-type
    value measured once.
    """
    doc_ids = sorted({d.doc_id for d in docs})
    m4 = _mean([metrics.type_stability(docs, i) for i in doc_ids])
    header = (f"{'type':<20}{'M1 merge':>10}{'M2 words':>10}{'M3 /doc':>10}"
              f"{'M5 cv':>10}")
    lines = [
        f"documents: {len(doc_ids)}   results: {len(docs)}",
        f"M4 type stability: {m4:.2f}   (mean over documents)",
        "M5 cv below is also a mean over documents.",
        "",
        header,
        "-" * len(header),
    ]
    for t in types:
        m5 = _mean([metrics.count_cv(docs, i, t) for i in doc_ids])
        lines.append(f"{t:<20}"
                     f"{metrics.mergeability(docs, t):>10.2f}"
                     f"{metrics.median_name_words(docs, t):>10.1f}"
                     f"{metrics.volume_per_doc(docs, t):>10.1f}"
                     f"{m5:>10.2f}")
    return "\n".join(lines)
