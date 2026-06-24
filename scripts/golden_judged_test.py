# ABOUTME: Local (ollama/gemma4) end-to-end test of the judged golden loop (_build_golden_set_judged).
# ABOUTME: Confirms the generate→judge→reflect loop runs on gemma4 and records the expected artifacts.
#
#   cd worker && .venv/bin/python ../scripts/golden_judged_test.py --domain business/marketing/branding --chunks 5 --iterations 1

import argparse, asyncio, json, os, shutil, uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Force LOCAL ollama/gemma4 regardless of .env (which is bedrock).
os.environ["ANTHROPIC_BACKEND"] = "ollama"
os.environ["CLASSIFICATION_MODEL"] = "gemma4:26b"
os.environ["EXTRACTION_MODEL"] = "gemma4:e4b"
os.environ["OLLAMA_URL"] = "http://localhost:11434"

from src.config import get_settings  # noqa: E402
from src.db import get_connection  # noqa: E402
from src.jobs.simmer_general import _build_golden_set_judged, _discover_domain_types  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--chunks", type=int, default=5)
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--source-db", default=str(Path.home() / "orrery-data" / "orrery.db"))
    args = ap.parse_args()

    settings = get_settings()
    print(f"backend={settings.anthropic_backend} classify={settings.classification_model} extract={settings.extraction_model}", flush=True)

    tmp_db = REPO / "scratch_golden_judged.db"
    shutil.copy(args.source_db, tmp_db)
    job_id = str(uuid.uuid4())
    conn = get_connection(str(tmp_db))
    conn.execute("INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'simmer_domain', ?, 'running', ?)",
                 (job_id, args.domain, json.dumps({"domain": args.domain})))
    rows = conn.execute(
        """SELECT c.id, c.text, d.title FROM chunks c
           JOIN documents d ON c.document_id = d.id
           JOIN document_domains dd ON d.id = dd.document_id
           WHERE dd.domain_path = ? AND d.status IN ('classified','extracted','enriched')
           ORDER BY c.id LIMIT ?""", (args.domain, args.chunks)).fetchall()
    conn.commit(); conn.close()
    if not rows:
        print(f"No chunks for {args.domain}"); return
    print(f"Sample: {len(rows)} chunks from {args.domain}", flush=True)

    print("Discovering domain types ...", flush=True)
    domain_types = await _discover_domain_types(rows, args.domain, settings, str(tmp_db))
    print(f"domain types ({len(domain_types.splitlines()) if domain_types else 0}):\n{domain_types}\n", flush=True)

    print("=== Running judged golden loop ===", flush=True)
    golden = await _build_golden_set_judged(
        rows, settings, job_id, str(tmp_db), args.iterations,
        taxonomy_hint=(domain_types or None), domain_path=args.domain)

    # Dump recorded artifacts (what the pipeline UI reads)
    conn = get_connection(str(tmp_db))
    iters = conn.execute(
        "SELECT iteration, scores, composite, asi, judge_mode, regressed FROM simmer_iterations "
        "WHERE job_id=? AND phase='golden_set' ORDER BY iteration", (job_id,)).fetchall()
    print("\n=== golden_set iterations recorded ===")
    for it in iters:
        print(f"  iter {it[0]}: composite={it[2]} scores={it[1]} regressed={bool(it[5])} judge_mode={it[4]}")
        print(f"          asi={ (it[3] or '')[:160]!r}")
        cds = conn.execute("SELECT criterion, score, seed_score FROM simmer_criterion_details cd "
                           "JOIN simmer_iterations si ON cd.iteration_id=si.id "
                           "WHERE si.job_id=? AND si.iteration=? AND si.phase='golden_set'", (job_id, it[0])).fetchall()
        for cd in cds:
            print(f"            - {cd[0]}: {cd[1]}/10 (seed {cd[2]})")
    conn.close()
    print("\n=== FINAL GOLDEN ===")
    print(golden[:1500])
    tmp_db.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
