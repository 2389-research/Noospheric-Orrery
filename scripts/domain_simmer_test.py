# ABOUTME: Local (ollama/gemma4) end-to-end test of run_simmer_domain — BOTH phases through the judged loop.
# ABOUTME: Confirms golden_set + extraction_spec iterations record scores/ASI and a spec is stored.
#
#   cd worker && .venv/bin/python ../scripts/domain_simmer_test.py --domain business/marketing/branding --iterations 1

import argparse, asyncio, json, os, shutil, uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ["ANTHROPIC_BACKEND"] = "ollama"
os.environ["CLASSIFICATION_MODEL"] = "gemma4:26b"
os.environ["EXTRACTION_MODEL"] = "gemma4:e4b"
os.environ["OLLAMA_URL"] = "http://localhost:11434"
os.environ["SPECS_DIR"] = str(REPO / "scratch_specs")

from src.config import get_settings  # noqa: E402
from src.db import get_connection  # noqa: E402
from src.jobs.simmer_domain import run_simmer_domain  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--source-db", default=str(Path.home() / "orrery-data" / "orrery.db"))
    args = ap.parse_args()

    (REPO / "scratch_specs").mkdir(exist_ok=True)
    settings = get_settings()  # specs_dir comes from SPECS_DIR env (set above)

    tmp_db = REPO / "scratch_domain_simmer.db"
    shutil.copy(args.source_db, tmp_db)
    job_id = str(uuid.uuid4())
    conn = get_connection(str(tmp_db))
    conn.execute("INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'simmer_domain', ?, 'running', ?)",
                 (job_id, args.domain, json.dumps({"domain": args.domain, "iterations": args.iterations})))
    conn.commit(); conn.close()

    job = {"id": job_id, "type": "simmer_domain", "target": args.domain,
           "config": json.dumps({"domain": args.domain, "iterations": args.iterations})}
    print(f"=== run_simmer_domain {args.domain} (iters={args.iterations}) ===", flush=True)
    await run_simmer_domain(job, str(tmp_db))

    conn = get_connection(str(tmp_db))
    for phase in ("golden_set", "extraction_spec"):
        iters = conn.execute(
            "SELECT iteration, scores, composite, asi, regressed FROM simmer_iterations "
            "WHERE job_id=? AND phase=? ORDER BY iteration", (job_id, phase)).fetchall()
        print(f"\n=== {phase} ({len(iters)} iterations) ===")
        for it in iters:
            print(f"  iter {it[0]}: composite={it[2]} scores={it[1]} regressed={bool(it[4])}")
            print(f"          asi={(it[3] or '')[:140]!r}")
    spec = conn.execute("SELECT version, score, length(spec_content) FROM specs WHERE domain_path=?",
                        (args.domain,)).fetchone()
    print(f"\nstored spec: version={spec[0] if spec else None} score={spec[1] if spec else None} chars={spec[2] if spec else None}")
    batch = conn.execute("SELECT id FROM jobs WHERE type='extract_batch' AND target=?", (args.domain,)).fetchone()
    print(f"queued extract_batch: {bool(batch)}")
    conn.close()
    tmp_db.unlink(missing_ok=True)
    print("\nDONE")


if __name__ == "__main__":
    asyncio.run(main())
