#!/usr/bin/env python
"""Run a full simmer (Phase 1 + Phase 2) and report results.

Usage:
  source /tmp/run-orchestrator.sh
  ANTHROPIC_BACKEND=bedrock uv run python run_simmer_test.py
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

# Ensure worker root on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.db import init_db, get_connection
from src.config import get_settings
from src.jobs.simmer_general import run_simmer_general


async def main():
    settings = get_settings()
    db_path = settings.db_path

    # Check we have docs
    conn = get_connection(db_path)
    doc_count = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE status IN ('classified', 'extracted', 'enriched')"
    ).fetchone()[0]
    print(f"Database: {db_path}")
    print(f"Available documents: {doc_count}")

    if doc_count < 3:
        print("ERROR: Need at least 3 classified/extracted docs to simmer.")
        conn.close()
        sys.exit(1)

    # Create a test job
    job_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'simmer_general', 'general', 'running', NULL)",
        (job_id,),
    )
    conn.commit()
    conn.close()

    print(f"\nJob ID: {job_id}")
    print(f"Specs dir: {settings.specs_dir}")
    print(f"Iterations: {settings.simmer_iterations}")
    print(f"Extraction model: {settings.extraction_model}")
    print("=" * 60)
    print("Starting full simmer (Phase 1: Golden Set + Phase 2: Extraction Spec)...")
    print("=" * 60)

    try:
        await run_simmer_general({"id": job_id, "type": "simmer_general", "target": "general", "config": None}, db_path)
    except Exception as e:
        print(f"\nSIMMER FAILED: {e}")
        # Mark job as failed
        conn = get_connection(db_path)
        conn.execute("UPDATE jobs SET status = 'failed' WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        raise

    # Mark job completed
    conn = get_connection(db_path)
    conn.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (job_id,))
    conn.commit()

    # Report results
    print("\n" + "=" * 60)
    print("SIMMER COMPLETE — RESULTS")
    print("=" * 60)

    # Read golden set
    specs_dir = Path(settings.specs_dir)
    golden_path = specs_dir / "general_golden_set.md"
    if golden_path.exists():
        golden_text = golden_path.read_text()
        print(f"\n--- Golden Set ({len(golden_text)} chars) ---")
        print(golden_text[:2000])
        if len(golden_text) > 2000:
            print(f"... ({len(golden_text) - 2000} more chars)")

    # Read spec
    spec_row = conn.execute(
        "SELECT spec_content, score FROM specs WHERE domain_path IS NULL ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if spec_row:
        print(f"\n--- Extraction Spec (score: {spec_row[1]}/10) ---")
        print(spec_row[0][:2000])

    # Read iterations
    iterations = conn.execute(
        "SELECT phase, iteration, scores, composite, key_change FROM simmer_iterations WHERE job_id = ? ORDER BY phase, iteration",
        (job_id,),
    ).fetchall()

    print(f"\n--- Iteration Trajectory ({len(iterations)} total) ---")
    current_phase = None
    for phase, iteration, scores, composite, key_change in iterations:
        if phase != current_phase:
            current_phase = phase
            print(f"\n  Phase: {phase}")
        scores_dict = json.loads(scores) if scores else {}
        scores_str = ", ".join(f"{k}={v}" for k, v in scores_dict.items())
        print(f"    iter {iteration}: {composite}/10 [{scores_str}] — {key_change or 'seed'}")

    # Show evaluator outputs if they exist
    eval_dirs = sorted((specs_dir / "general_spec").glob("eval-*"))
    if eval_dirs:
        print(f"\n--- Evaluator Outputs ({len(eval_dirs)} iterations) ---")
        for eval_dir in eval_dirs:
            json_files = list(eval_dir.glob("*.json"))
            print(f"  {eval_dir.name}: {len(json_files)} doc outputs")
            # Show aggregate from one file
            for jf in json_files[:1]:
                entities = json.loads(jf.read_text())
                print(f"    Sample ({jf.name}): {len(entities)} entities extracted")

    # Check if batch extraction was queued
    batch = conn.execute("SELECT id, status FROM jobs WHERE type = 'extract_batch' ORDER BY rowid DESC LIMIT 1").fetchone()
    if batch:
        print(f"\n--- Batch extraction queued: {batch[0][:8]}... (status: {batch[1]}) ---")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
