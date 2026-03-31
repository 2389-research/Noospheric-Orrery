"""Cloud Run Job entry point.

Receives JOB_ID and WORKSPACE_ID as env vars.
Reads job from Firestore, executes it, writes results back.
"""
import os
import sys
import asyncio
import traceback
from datetime import datetime, timezone
from google.cloud import firestore

db = firestore.Client()


def get_job_ref(workspace_id: str, job_id: str):
    return db.collection(f"workspaces/{workspace_id}/jobs").document(job_id)


async def run():
    job_id = os.environ.get("JOB_ID")
    workspace_id = os.environ.get("WORKSPACE_ID")

    if not job_id or not workspace_id:
        print("ERROR: JOB_ID and WORKSPACE_ID env vars required", file=sys.stderr)
        sys.exit(1)

    job_ref = get_job_ref(workspace_id, job_id)
    job_doc = job_ref.get()

    if not job_doc.exists:
        print(f"ERROR: Job {job_id} not found in workspace {workspace_id}", file=sys.stderr)
        sys.exit(1)

    job = job_doc.to_dict()

    # Idempotency guard
    if job["status"] in ("running", "completed", "failed"):
        print(f"Job {job_id} already in status {job['status']}, skipping")
        return

    print(f"Starting job {job_id} ({job['type']}) for workspace {workspace_id}", flush=True)
    job_ref.update({
        "status": "running",
        "startedAt": datetime.now(timezone.utc),
    })

    try:
        job_type = job["type"]
        if job_type == "simmer_general":
            from worker.jobs.simmer_general import run_simmer_general
            await run_simmer_general(db, workspace_id, job_id, job)
        elif job_type == "simmer_domain":
            from worker.jobs.simmer_domain import run_simmer_domain
            await run_simmer_domain(db, workspace_id, job_id, job)
        elif job_type == "extract_batch":
            from worker.jobs.extract_batch import run_extract_batch
            await run_extract_batch(db, workspace_id, job_id, job)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

        job_ref.update({
            "status": "completed",
            "completedAt": datetime.now(timezone.utc),
        })
        print(f"Job {job_id} completed", flush=True)

    except Exception as e:
        job_ref.update({
            "status": "failed",
            "completedAt": datetime.now(timezone.utc),
            "result": {"error": str(e)},
        })
        print(f"Job {job_id} failed: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
