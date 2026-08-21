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
