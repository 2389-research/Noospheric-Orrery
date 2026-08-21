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
