import os
import asyncio
import time
import traceback
from pathlib import Path
from .config import get_settings
from .db import init_db, get_connection
from .jobs.runner import pick_next_job, mark_job_running, mark_job_completed, mark_job_failed


def _configure_gateway_for_simmer_sdk() -> None:
    """simmer-sdk doesn't know our 'gateway' backend — it only speaks anthropic/bedrock/ollama.
    When ANTHROPIC_BACKEND=gateway, route simmer-sdk's Anthropic client through the gateway
    by setting ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY. The jobs then pass api_provider='anthropic'."""
    s = get_settings()
    if s.anthropic_backend == "gateway" and s.gateway_url and s.gateway_api_key:
        os.environ["ANTHROPIC_BASE_URL"] = s.gateway_url
        os.environ["ANTHROPIC_API_KEY"] = s.gateway_api_key


_configure_gateway_for_simmer_sdk()

async def handle_job(job: dict, db_path: str) -> None:
    if job["type"] == "simmer_general":
        from .jobs.simmer_general import run_simmer_general
        await run_simmer_general(job, db_path)
    elif job["type"] == "simmer_domain":
        from .jobs.simmer_domain import run_simmer_domain
        await run_simmer_domain(job, db_path)
    elif job["type"] == "simmer_domain_image":
        from .jobs.simmer_domain_image import run_simmer_domain_image
        await run_simmer_domain_image(job, db_path)
    elif job["type"] == "extract_batch":
        from .jobs.extract_batch import run_extract_batch
        await run_extract_batch(job, db_path)
    elif job["type"] == "extract_batch_image":
        from .jobs.extract_batch_image import run_extract_batch_image
        await run_extract_batch_image(job, db_path)
    elif job["type"] == "ingest_repo":
        from .jobs.ingest_repo import run_ingest_repo
        await run_ingest_repo(job, db_path)
    elif job["type"] == "ingest_tracker_runs":
        from .jobs.ingest_tracker_runs import run_ingest_tracker_runs
        await run_ingest_tracker_runs(job, db_path)
    elif job["type"] == "judge_corrections":
        from .jobs.graph_repair import run_judge_corrections
        await run_judge_corrections(job, db_path)
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

    from orrery_relay import Relay
    from .jobs.graph_repair import run_judge_sweep
    from .jobs.normalization_judge import resolve_judge_relay, run_normalization_judge_sweep
    relay = Relay.from_settings(settings)
    last_sweep = 0.0  # 0 → sweep on the first iteration

    while True:
        # Scan all workspace DBs for queued jobs
        db_paths = _find_workspace_dbs(settings.db_path)
        did_work = False   # did a REAL job run this pass? (this gates the idle judge)

        for db_path in db_paths:
            try:
                init_db(db_path)
                conn = get_connection(db_path)
                job = pick_next_job(conn)

                if job:
                    did_work = True
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

        now = time.monotonic()
        if now - last_sweep >= settings.judge_sweep_interval_seconds:
            last_sweep = now
            try:
                result = await run_judge_sweep(db_paths, relay, settings.classification_model)
                if result["judged"] or result["failed"]:
                    print(f"judge sweep: judged {result['judged']}, {result['failed']} failed/left un-judged", flush=True)
            except Exception as e:
                print(f"judge sweep error: {e}", flush=True)

        # Low-priority background work: drain the normalization review backlog, but ONLY
        # when no real job ran this pass. The point of the gate is resource contention —
        # on a local model the judge and an extraction would fight over the same GPU, and
        # the judge is never the urgent one. One bounded batch per pass; while it is
        # draining, poll again quickly (still checking for jobs FIRST) instead of idling
        # the full interval, so a backlog clears without delaying real work.
        norm_did = False
        if settings.normalization_judge_mode != "off" and not did_work:
            try:
                # Local model if Ollama has it, else the cloud model — re-checked on a TTL
                # rather than fixed at startup, since Ollama comes and goes. The probe
                # blocks, so it runs in a thread: the poll loop must not stall on a socket
                # timeout. Inside the try on purpose — a resolve failure has to be logged
                # and retried, never crash poll_loop and take the worker down with it.
                judge_relay, judge_model, judge_src = await asyncio.to_thread(
                    resolve_judge_relay, settings, relay)
                nr = await run_normalization_judge_sweep(
                    db_paths, judge_relay, judge_model,
                    batch_size=settings.normalization_judge_batch,
                    mode=settings.normalization_judge_mode,
                    min_confidence=settings.normalization_judge_min_confidence,
                    temperature=settings.normalization_judge_temperature,
                    max_attempts=settings.normalization_judge_max_attempts,
                )
                if nr["pairs"]:
                    norm_did = True
                    ws = Path(nr.get("workspace", "")).parent.name
                    print(f"norm_judge[{settings.normalization_judge_mode}/{judge_src}:"
                          f"{judge_model}] ws={ws}: judged {nr['judged']}, "
                          f"kept-resolved {nr['kept_resolved']}, "
                          f"merge-advised {nr['merge_advised']}, unsure {nr['unsure']}, "
                          f"{nr['failed']} failed", flush=True)
            except Exception as e:
                print(f"norm_judge error: {e}", flush=True)

        await asyncio.sleep(1 if norm_did else settings.worker_poll_interval)

def main():
    asyncio.run(poll_loop())

if __name__ == "__main__":
    main()
