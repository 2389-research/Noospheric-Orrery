# ABOUTME: CLI for the charter evaluation: collect (live, slow), sample (for labelling),
# ABOUTME: report (pure). Collection and scoring are separate commands on purpose.
import argparse
import sys

from . import harness, metrics, report, sample

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
    r.add_argument("--variant", choices=["v1", "A", "B"],
                   help="score only this arm. Required when the results file holds more "
                        "than one variant — the decision rule is defined for one arm.")

    s = sub.add_parser("sample")
    s.add_argument("--results", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--per-type", type=int, default=25)
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
    found = sorted({d.variant for d in docs})
    if a.variant:
        docs = metrics.filter_variant(docs, a.variant)
        variant = a.variant
    elif len(found) > 1:
        # The decision rule is defined for ONE arm. Scoring a mixed file would silently
        # average the arms together, so refuse rather than guess.
        print(f"results hold {len(found)} variants ({', '.join(found)}): "
              f"pass --variant to choose one", file=sys.stderr)
        return 2
    else:
        variant = found[0] if found else "(none)"

    print(f"variant: {variant}   ({len(docs)} results)")
    print()
    print(report.render_table(docs, DECL_TYPES))
    print()
    print(f"M7 latency: {metrics.mean_latency_s(docs):.1f}s per document (mean)")
    print()
    if a.precision_csv:
        prec = sample.precision_from_csv(a.precision_csv, report.DECISION_TYPE)
        d = report.decide(docs, prec)
        if d.ship == report.INSUFFICIENT_DATA:
            print(f"{report.INSUFFICIENT_DATA}: no decision")
            for reason in d.reasons:
                print(f"  {reason}")
        else:
            print(f"SHIP {d.ship}   m1={d.m1:.4f} m2={d.m2:.1f} m6={d.m6:.4f}")
            for reason in d.reasons:
                print(f"  fail: {reason}")
    else:
        print("no --precision-csv: M6 unmeasured, decision withheld")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
