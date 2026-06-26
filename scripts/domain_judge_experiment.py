#!/usr/bin/env python3
# ABOUTME: Run the REAL run_simmer_domain flow varying ONLY the judge config (env knobs), isolated on
# ABOUTME: DB copies with a pinned chunk sample. Captures each variant's golden + spec + per-round ASIs.
#
# This is the valid way to compare judge configurations: it exercises the actual domain-simmer
# pipeline (Phase 1 golden + Phase 2 spec, both judged) on identical input, so the judge is the only
# variable. Evaluate the captured artifacts qualitatively (don't rely on exact-match F1).
#
# Usage (must use the worker venv so simmer_sdk / orrery_relay import):
#   ANTHROPIC_BACKEND=ollama OLLAMA_URL=http://localhost:11434 \
#   CLASSIFICATION_MODEL=gemma4:26b EXTRACTION_MODEL=gemma4:e4b \
#   worker/.venv/bin/python scripts/domain_judge_experiment.py \
#       --domain business/product_development/strategy \
#       --src-db ~/orrery-data/orrery.db --out ./judge_exp \
#       --chunks 10 --iterations 2 \
#       --variants "floor:1x1,floor2:1x1,board:2x1,board2:2x1"
#
# Each --variants entry is "name:NxK"; JUDGE_PANEL defaults to 'auto' (override with --panel).

import argparse, asyncio, json, os, shutil, sqlite3, sys, time, traceback, uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "worker"))


def build_pinned_base(src_db, out, domain, n_chunks):
    """Copy the DB and trim DOMAIN's valid-status chunk pool to exactly n_chunks (deterministic)."""
    base = str(out / "base_pinned.db")
    shutil.copy(os.path.expanduser(src_db), base)
    c = sqlite3.connect(base)
    pool = [r[0] for r in c.execute(
        """SELECT c.id FROM chunks c JOIN documents d ON c.document_id=d.id
           JOIN document_domains dd ON d.id=dd.document_id
           WHERE dd.domain_path=? AND d.status IN ('classified','extracted','enriched')
           ORDER BY c.id""", (domain,)).fetchall()]
    keep = pool[:n_chunks]
    qmarks = ",".join("?" * len(keep))
    c.execute(
        f"""DELETE FROM chunks WHERE id IN
              (SELECT c.id FROM chunks c JOIN documents d ON c.document_id=d.id
               JOIN document_domains dd ON d.id=dd.document_id
               WHERE dd.domain_path=? AND d.status IN ('classified','extracted','enriched'))
            AND id NOT IN ({qmarks})""", (domain, *keep))
    c.commit(); c.close()
    print(f"[pin] {domain}: pool trimmed to {len(keep)} chunks", flush=True)
    return base, keep


def capture(run_db, job_id, domain, vout):
    c = sqlite3.connect(run_db)
    iters = [dict(iteration=r[0], phase=r[1], composite=r[2],
                  scores=json.loads(r[3]) if r[3] else {}, asi=r[4], judge_mode=r[5])
             for r in c.execute(
                 "SELECT iteration, phase, composite, scores, asi, judge_mode FROM simmer_iterations "
                 "WHERE job_id=? ORDER BY phase, iteration", (job_id,)).fetchall()]
    spec = c.execute("SELECT version, score, spec_content, golden_set FROM specs "
                     "WHERE domain_path=? ORDER BY version DESC LIMIT 1", (domain,)).fetchone()
    c.close()
    (vout / "iters.json").write_text(json.dumps(iters, indent=2))
    if spec:
        (vout / "spec.md").write_text(spec[2] or "")
        (vout / "golden.md").write_text(spec[3] or "")
        return {"spec_version": spec[0], "spec_score": spec[1], "n_iters": len(iters)}
    return {"spec_version": None, "note": "no spec (domain discovery may have skipped)", "n_iters": len(iters)}


async def run_variant(name, n, k, panel, base_db, out, domain, iterations):
    vout = out / name; vout.mkdir(exist_ok=True)
    run_db = str(vout / "run.db"); shutil.copy(base_db, run_db)
    specs_dir = str(vout / "specs"); Path(specs_dir).mkdir(exist_ok=True)
    os.environ.update({"JUDGE_COUNT": str(n), "JUDGE_SAMPLES": str(k), "JUDGE_PANEL": panel,
                       "DB_PATH": run_db, "SPECS_DIR": specs_dir})
    from src.jobs.simmer_domain import run_simmer_domain
    job_id = str(uuid.uuid4())
    job = {"id": job_id, "type": "simmer_domain", "target": domain, "status": "running",
           "config": json.dumps({"domain": domain, "iterations": iterations, "resume": False})}
    print(f"\n===== {name}  N={n} K={k} panel={panel}  job={job_id[:8]} =====", flush=True)
    t0 = time.time(); summary = {"variant": name, "n": n, "k": k, "panel": panel, "job_id": job_id}
    try:
        await run_simmer_domain(job, run_db)
        summary.update(capture(run_db, job_id, domain, vout)); summary["status"] = "ok"
    except Exception as e:
        summary.update({"status": "error", "error": str(e), "trace": traceback.format_exc()[-1500:]})
        try: summary.update(capture(run_db, job_id, domain, vout))
        except Exception: pass
        print(f"[{name}] ERROR: {e}", flush=True)
    summary["elapsed_s"] = round(time.time() - t0, 1)
    (vout / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[{name}] done {summary['elapsed_s']}s status={summary['status']}", flush=True)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--src-db", default="~/orrery-data/orrery.db")
    ap.add_argument("--out", required=True, help="Output dir for DB copies + captured artifacts.")
    ap.add_argument("--chunks", type=int, default=10)
    ap.add_argument("--iterations", type=int, default=2)
    ap.add_argument("--panel", default="auto")
    ap.add_argument("--variants", default="floor:1x1,board:2x1",
                    help="Comma list of name:NxK (e.g. 'floor:1x1,board:2x1').")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    base_db, keep = build_pinned_base(args.src_db, out, args.domain, args.chunks)
    manifest = {"domain": args.domain, "pinned_chunks": keep, "iterations": args.iterations, "variants": []}
    for entry in args.variants.split(","):
        name, cell = entry.split(":"); n, k = (int(x) for x in cell.lower().split("x"))
        manifest["variants"].append(
            asyncio.run(run_variant(name, n, k, args.panel, base_db, out, args.domain, args.iterations)))
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("\n==== MANIFEST ====")
    print(json.dumps([{kk: v.get(kk) for kk in ("variant", "status", "spec_score", "elapsed_s", "n_iters")}
                      for v in manifest["variants"]], indent=2))


if __name__ == "__main__":
    main()
