import os
import asyncio
import traceback
from pathlib import Path
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
    elif job["type"] == "simmer_general_image":
        from .jobs.simmer_general import run_simmer_general_image
        await run_simmer_general_image(job, db_path)
    elif job["type"] == "extract_batch":
        from .jobs.extract_batch import run_extract_batch
        await run_extract_batch(job, db_path)
    elif job["type"] == "extract_batch_image":
        from .jobs.extract_batch_image import run_extract_batch_image
        await run_extract_batch_image(job, db_path)
    else:
        raise ValueError(f"Unknown job type: {job['type']}")


def _find_workspace_dbs(base_db_path: str) -> list[str]:
    """Find all workspace SQLite databases.

    Checks both:
    - Multi-workspace layout: {data_dir}/workspaces/*/orrery.db
    - Legacy flat layout: {data_dir}/orrery.db
    """
    base_dir = os.path.dirname(base_db_path)
    db_paths = []

    # Multi-workspace
    ws_dir = os.path.join(base_dir, "workspaces")
    if os.path.isdir(ws_dir):
        for ws_name in os.listdir(ws_dir):
            ws_db = os.path.join(ws_dir, ws_name, "orrery.db")
            if os.path.isfile(ws_db):
                db_paths.append(ws_db)

    # Legacy flat
    if os.path.isfile(base_db_path) and base_db_path not in db_paths:
        db_paths.append(base_db_path)

    return db_paths


async def poll_loop():
    settings = get_settings()
    print(f"Worker started, polling every {settings.worker_poll_interval}s", flush=True)

    while True:
        # Scan all workspace DBs for queued jobs
        db_paths = _find_workspace_dbs(settings.db_path)

        for db_path in db_paths:
            try:
                init_db(db_path)
                conn = get_connection(db_path)
                job = pick_next_job(conn)

                if job:
                    ws_name = Path(db_path).parent.name
                    print(f"Picked up job {job['id']} ({job['type']}) in workspace {ws_name}", flush=True)
                    mark_job_running(conn, job["id"])
                    conn.close()
                    try:
                        await handle_job(job, db_path)
                        conn = get_connection(db_path)
                        mark_job_completed(conn, job["id"])
                        print(f"Job {job['id']} completed", flush=True)
                    except Exception as e:
                        conn = get_connection(db_path)
                        mark_job_failed(conn, job["id"], traceback.format_exc())
                        print(f"Job {job['id']} failed: {e}", flush=True)
                    finally:
                        conn.close()
                else:
                    conn.close()
            except Exception as e:
                print(f"Error polling {db_path}: {e}", flush=True)

        await asyncio.sleep(settings.worker_poll_interval)

def main():
    asyncio.run(poll_loop())

if __name__ == "__main__":
    main()
