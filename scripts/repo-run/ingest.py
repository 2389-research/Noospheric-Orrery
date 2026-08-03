#!/usr/bin/env python3
# ABOUTME: Driver + observer for a repo-ingest run against a running Orrery instance.
# ABOUTME: POST /ingest/repo per repo, poll GET /jobs to completion, capture outcomes + snapshots.
#
# Stdlib only (urllib) — no pip install needed. Run AFTER prepare.sh and `docker compose up`.
#
#   python scripts/repo-run/ingest.py
#   ORRERY_URL=http://localhost:8100 WORKSPACE=default python scripts/repo-run/ingest.py
#
# Outputs (per run, under --out, default scripts/repo-run/runs/<timestamp>/):
#   run.jsonl             one line per repo: request, ingest + extract results, timings
#   stats.json            GET /stats snapshot at end
#   domains.json          GET /domains snapshot
#   graph.json            GET /graph snapshot (the built galaxy)
#   repo-<name>.json      GET /repos/<repo_id>/structure per repo

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def safe_name(name):
    """A repo name must be a single, safe path segment (it's appended to the
    container ingest path) — reject traversal like ``../../etc``."""
    if name in (".", "..") or not _SAFE_NAME.match(name):
        raise SystemExit(f"unsafe repo name {name!r}: must be a single path segment [A-Za-z0-9._-]")
    return name


def as_dict(v):
    """Parse a job-result value into a dict, tolerating already-parsed dicts and
    unparseable strings (so a malformed result never crashes the observer)."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v:
        try:
            return json.loads(v)
        except Exception:
            return {}
    return {}


def read_repos(path):
    repos = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            repos.append((parts[0], parts[1] if len(parts) > 1 else ""))
    return repos


def http(url, method="GET", body=None, workspace="default", timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Workspace-Id", workspace)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:500]}
    except Exception as e:
        return 0, {"error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    _local = os.path.join(HERE, "repos.local.txt")
    default_repos = _local if os.path.exists(_local) else os.path.join(HERE, "repos.txt")
    ap.add_argument("--repos", default=default_repos)
    ap.add_argument("--url", default=os.environ.get("ORRERY_URL", "http://localhost:8100"))
    ap.add_argument("--workspace", default=os.environ.get("WORKSPACE", "default"))
    ap.add_argument("--data-prefix", default=os.environ.get("DATA_PREFIX", "/data/repos"),
                    help="container-visible path where prepare.sh put the repos")
    ap.add_argument("--out", default=os.path.join(HERE, "runs", time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--poll", type=float, default=5.0, help="poll interval seconds")
    ap.add_argument("--timeout", type=float, default=2400.0, help="overall wait budget seconds")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    repos = read_repos(args.repos)
    print(f"Orrery: {args.url} (workspace={args.workspace})  |  {len(repos)} repos  |  out={args.out}\n")

    # 1. Fire ingest for each repo.
    tracked = {}  # name -> {repo_id, ingest_job, started}
    for name, _ in repos:
        path = f"{args.data_prefix}/{safe_name(name)}"
        status, resp = http(f"{args.url}/ingest/repo", "POST",
                            {"path": path, "name": name}, args.workspace)
        if status in (200, 201, 202) and resp and "job_id" in resp:
            tracked[name] = {"repo_id": resp["repo_id"], "ingest_job": resp["job_id"],
                             "started": time.monotonic()}
            print(f"  queued  {name:<14} repo={resp['repo_id'][:8]} job={resp['job_id'][:8]}")
        else:
            tracked[name] = {"error": f"HTTP {status}: {resp}"}
            print(f"  FAILED  {name:<14} HTTP {status}: {resp}")

    # 2. Poll jobs to completion. A repo is "done" when its ingest_repo job AND the
    #    downstream extract_batch job (target=repo_id) are both terminal.
    print("\nPolling jobs ...")
    deadline = time.monotonic() + args.timeout
    done = set()
    while len(done) < len([n for n in tracked if "repo_id" in tracked[n]]) and time.monotonic() < deadline:
        _, jobs = http(f"{args.url}/jobs", workspace=args.workspace)
        if not isinstance(jobs, list):  # connection/HTTP error returned {"error": ...} — retry until deadline
            time.sleep(args.poll)
            continue
        by_id = {j["id"]: j for j in jobs}
        for name, t in tracked.items():
            if "repo_id" not in t or name in done:
                continue
            ij = by_id.get(t["ingest_job"], {})
            ing_status = ij.get("status")
            # find the extract_batch job for this repo (created after ingest completes)
            xb = next((j for j in jobs if j["type"] == "extract_batch" and j["target"] == t["repo_id"]), None)
            xb_status = xb["status"] if xb else None
            ing_terminal = ing_status in ("completed", "failed")
            xb_terminal = xb_status in ("completed", "failed")
            if ing_terminal and (xb_terminal or ing_status == "failed"):
                t["ingest_result"] = ij.get("results")
                t["ingest_status"] = ing_status
                t["extract_result"] = xb.get("results") if xb else None
                t["extract_status"] = xb_status
                t["elapsed_s"] = round(time.monotonic() - t["started"], 1)
                done.add(name)
                print(f"  done    {name:<14} ingest={ing_status} extract={xb_status} ({t['elapsed_s']}s)")
        if len(done) < len([n for n in tracked if "repo_id" in tracked[n]]):
            time.sleep(args.poll)

    # 3. Write per-repo run log.
    run_path = os.path.join(args.out, "run.jsonl")
    with open(run_path, "w") as f:
        for name, t in tracked.items():
            rec = {"name": name, **t}
            rec.pop("started", None)
            # parse embedded result JSON strings for readability (tolerant)
            for k in ("ingest_result", "extract_result"):
                if rec.get(k) is not None:
                    rec[k] = as_dict(rec[k])
            f.write(json.dumps(rec) + "\n")

    # 4. Snapshot the resulting graph state.
    for name, url in [("stats", "/stats"), ("domains", "/domains"), ("graph", "/graph")]:
        _, data = http(f"{args.url}{url}", workspace=args.workspace)
        with open(os.path.join(args.out, f"{name}.json"), "w") as f:
            json.dump(data, f, indent=2)
    for name, t in tracked.items():
        if "repo_id" in t:
            _, data = http(f"{args.url}/repos/{t['repo_id']}/structure", workspace=args.workspace)
            with open(os.path.join(args.out, f"repo-{name}.json"), "w") as f:
                json.dump(data, f, indent=2)

    # 5. Summary.
    print("\n=== summary ===")
    for name, t in tracked.items():
        if "error" in t and "repo_id" not in t:
            print(f"  {name:<14} ERROR {t['error']}")
            continue
        ir = as_dict(t.get("ingest_result"))
        xr = as_dict(t.get("extract_result"))
        dom = ir.get("primary_domain", "?")
        ents = xr.get("entities_found", "?")
        print(f"  {name:<14} -> {dom:<40} entities={ents}  ({t.get('elapsed_s','?')}s)")
    incomplete = [n for n in tracked if "repo_id" in tracked[n] and n not in done]
    if incomplete:
        print(f"\n  ⚠️ still running / timed out: {incomplete}")
    print(f"\nWrote: {run_path} + stats/domains/graph/repo-* snapshots in {args.out}")


if __name__ == "__main__":
    sys.exit(main())
