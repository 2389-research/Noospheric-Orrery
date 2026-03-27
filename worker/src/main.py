import asyncio
import traceback
from .config import get_settings
from .db import init_db, get_connection
from .jobs.runner import pick_next_job, mark_job_running, mark_job_completed, mark_job_failed

async def handle_job(job: dict, db_path: str) -> None:
    if job["type"] == "simmer_general":
        from .jobs.simmer_general import run_simmer_general
        await run_simmer_general(job, db_path)
    elif job["type"] == "simmer_domain":
        from .jobs.simmer_domain import run_simmer_domain
        await run_simmer_domain(job, db_path)
    elif job["type"] == "extract_batch":
        from .jobs.extract_batch import run_extract_batch
        await run_extract_batch(job, db_path)
    else:
        raise ValueError(f"Unknown job type: {job['type']}")

async def poll_loop():
    settings = get_settings()
    init_db(settings.db_path)
    print(f"Worker started, polling every {settings.worker_poll_interval}s", flush=True)

    while True:
        conn = get_connection(settings.db_path)
        job = pick_next_job(conn)

        if job:
            print(f"Picked up job {job['id']} ({job['type']})", flush=True)
            mark_job_running(conn, job["id"])
            conn.close()
            try:
                await handle_job(job, settings.db_path)
                conn = get_connection(settings.db_path)
                mark_job_completed(conn, job["id"])
                print(f"Job {job['id']} completed", flush=True)
            except Exception as e:
                conn = get_connection(settings.db_path)
                mark_job_failed(conn, job["id"], traceback.format_exc())
                print(f"Job {job['id']} failed: {e}", flush=True)
            finally:
                conn.close()
        else:
            conn.close()

        await asyncio.sleep(settings.worker_poll_interval)

def main():
    asyncio.run(poll_loop())

if __name__ == "__main__":
    main()
