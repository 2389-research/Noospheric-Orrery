#!/usr/bin/env python3
# ABOUTME: Sequential driver for ingesting a directory of PDFs one at a time against a
# ABOUTME: running Orrery instance — avoids concurrent-request races with the orchestrator.
#
# Stdlib only (urllib) — no pip install needed. Run AFTER `docker compose up`.
#
#   python scripts/paper-run/ingest_papers.py
#   ORRERY_URL=http://localhost:8100 python scripts/paper-run/ingest_papers.py --dir pi0/papers
#
# Ingests are run ONE AT A TIME (waits for each response before starting the next) —
# the orchestrator has a known native-crash issue (SIGBUS) under concurrent requests
# (see CLAUDE.md), so this script deliberately never overlaps two in-flight ingests.
#
# If a request times out or the connection drops (the crash signature), the script
# polls /health until the orchestrator comes back, then moves on to the NEXT file —
# retrying the same file would just hit content-hash dedup against the
# already-created (partially processed) document from the crashed attempt.
#
# Output: one line per file printed as it completes, plus a JSON summary written to
# --out (default scripts/paper-run/runs/<timestamp>/run.json).

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.request
import urllib.error
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))


def build_multipart(field_name, filename, file_bytes):
    boundary = uuid.uuid4().hex
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts = []
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
    )
    parts.append(f"Content-Type: {mime_type}\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def wait_for_health(base_url, timeout_s=120, poll_s=2):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(poll_s)
    return False


def ingest_one(base_url, path, request_timeout_s):
    with open(path, "rb") as f:
        file_bytes = f.read()
    body, content_type = build_multipart("file", os.path.basename(path), file_bytes)
    req = urllib.request.Request(
        f"{base_url}/ingest", data=body, method="POST",
        headers={"Content-Type": content_type},
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=request_timeout_s) as resp:
            result = json.loads(resp.read().decode())
            return {"ok": True, "status": resp.status, "result": result, "elapsed_s": time.time() - started}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        return {"ok": False, "status": e.code, "error": detail, "elapsed_s": time.time() - started}
    except Exception as e:
        # Connection dropped / timed out — the orchestrator's known SIGBUS crash
        # signature under concurrent load. Not treated as a hard failure of the
        # script; the caller checks orchestrator health and moves to the next file.
        return {"ok": False, "status": None, "error": str(e), "elapsed_s": time.time() - started}


def main():
    parser = argparse.ArgumentParser(description="Sequentially ingest every PDF/DOCX in a directory")
    parser.add_argument("--dir", default="pi0/papers", help="Directory of files to ingest (default: pi0/papers)")
    parser.add_argument("--url", default=os.environ.get("ORRERY_URL", "http://localhost:8100"))
    parser.add_argument("--timeout", type=int, default=180, help="Per-file request timeout in seconds")
    parser.add_argument("--out", default=None, help="Output directory for run.json (default: scripts/paper-run/runs/<timestamp>)")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        raise SystemExit(f"Not a directory: {args.dir}")

    files = sorted(
        os.path.join(args.dir, name) for name in os.listdir(args.dir)
        if name.lower().endswith((".pdf", ".docx"))
    )
    if not files:
        raise SystemExit(f"No .pdf/.docx files found in {args.dir}")

    out_dir = args.out or os.path.join(HERE, "runs", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    run_log_path = os.path.join(out_dir, "run.json")

    print(f"Ingesting {len(files)} file(s) from {args.dir} against {args.url}, one at a time.")
    print(f"Run log: {run_log_path}\n")

    run_log = []
    for i, path in enumerate(files, 1):
        name = os.path.basename(path)
        if not wait_for_health(args.url):
            print(f"[{i}/{len(files)}] {name}: orchestrator not healthy, aborting run")
            break

        outcome = ingest_one(args.url, path, args.timeout)
        entry = {"file": name, **outcome}
        run_log.append(entry)

        if outcome["ok"]:
            r = outcome["result"]
            print(
                f"[{i}/{len(files)}] {name}: HTTP {outcome['status']} "
                f"entity_count={r.get('entity_count')} domains={r.get('domains')} "
                f"({outcome['elapsed_s']:.1f}s)"
            )
        else:
            print(
                f"[{i}/{len(files)}] {name}: FAILED status={outcome['status']} "
                f"error={outcome['error'][:200]!r} ({outcome['elapsed_s']:.1f}s)"
            )
            # Give the orchestrator a moment to fully restart if it crashed, so the
            # next file's health check doesn't race a container still coming up.
            time.sleep(3)

        with open(run_log_path, "w") as f:
            json.dump(run_log, f, indent=2)

    ok_count = sum(1 for e in run_log if e["ok"])
    print(f"\nDone: {ok_count}/{len(run_log)} succeeded. Full log at {run_log_path}")


if __name__ == "__main__":
    main()
