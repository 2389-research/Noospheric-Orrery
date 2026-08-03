# Repo-ingest run harness

A configurable, repeatable pipeline for pointing the Noospheric Orrery at a set of
git repos, then capturing the process exhaust and the resulting graph so runs are
observable and troubleshootable.

## What it captures (three layers)

1. **Raw call trace** — the worker emits the relay's per-LLM-call log
   (`orrery_relay | complete model=… tokens=in/out cache=create/read latency=…ms`)
   for every summarize / classify / extract call. Captured via `capture-logs.sh`.
2. **Structured per-repo outcomes** — `ingest.py` writes `run.jsonl`: one line per repo
   with the request, the `ingest_repo` result (classified domain + artifact counts) and
   the `extract_batch` result (entity counts), plus timings.
3. **Final graph snapshot** — `ingest.py` dumps `stats.json`, `domains.json`, `graph.json`,
   and `repo-<name>.json` (per-repo structure) at the end. Plus the viz at
   `http://localhost:3100/n/default/orrery`.

> **Docker Compose command:** examples below use `docker compose` (v2 plugin).
> If that errors (`unknown flag`), your machine only has the standalone binary —
> use `docker-compose` (hyphenated) for every compose command. `capture-logs.sh`
> auto-detects; the `up` command you run by hand does not.

## Smoke test first (cheap, one small repo)

Validate the whole path — HTTP ingest → job polling → log capture — on a single
small dir before the full run. [`repos.test.txt`](repos.test.txt) points at
`packages/orrery-codesum` (this repo's own subdir).

```bash
scripts/repo-run/prepare.sh scripts/repo-run/repos.test.txt   # copies codesum into ./data/repos/
docker compose up --build -d
scripts/repo-run/capture-logs.sh                              # terminal A — watch the relay trace stream
python scripts/repo-run/ingest.py --repos scripts/repo-run/repos.test.txt   # terminal B
```
Expect: in terminal A, `[ingest_repo] orrery-codesum: summarizing …`, a burst of
`orrery_relay | complete … cache=…` lines, `[ingest_repo] orrery-codesum -> software/developer-tools/code-analysis …`,
then `extract_batch` progress. In terminal B, a summary line and `run.jsonl` written.

## Configure the full run

Edit [`repos.txt`](repos.txt) — one `<name>  <local-git-path>` per line.

## Run

Everything runs from the repo root. Steps 3–5 are separate terminals.

```bash
# 1. Export each repo's up-to-date origin/main into ./data/repos/<name>
#    (non-destructive — does NOT touch your working checkout / feature branches)
scripts/repo-run/prepare.sh

# 2. (Re)build & start the stack — REBUILD is required, the worker/orchestrator
#    code changed (logging, summarize→classify reorder, job-result fix).
docker compose up --build -d

# 3. [terminal A] stream + save the raw call trace
scripts/repo-run/capture-logs.sh

# 4. [terminal B] drive the ingest + collect outcomes/snapshots
python scripts/repo-run/ingest.py

# 5. observe
open http://localhost:3100/n/default/orrery      # the galaxy
ls scripts/repo-run/runs/<timestamp>/            # run.jsonl + snapshots
```

## Knobs (env / flags on `ingest.py`)

| var / flag | default | meaning |
|---|---|---|
| `ORRERY_URL` | `http://localhost:8100` | orchestrator base URL |
| `WORKSPACE` | `default` | `X-Workspace-Id` header |
| `--data-prefix` | `/data/repos` | container path where `prepare.sh` put the repos |
| `--out` | `runs/<timestamp>` | output dir for `run.jsonl` + snapshots |
| `--poll` / `--timeout` | `5` / `2400` | job poll interval / overall wait budget (s) |

Config affecting the run itself lives in `.env` (gitignored):
`CLASSIFICATION_MODEL` / `EXTRACTION_MODEL`, and the sky-high
`GENERAL_SPEC_THRESHOLD` / `DOMAIN_SPEC_THRESHOLD` that keep auto domain-refinement
(simmer, which errors on Bedrock) from firing during a run.

## Reset

```bash
rm -rf ./data              # wipes the whole Orrery DB + docs + specs (fresh graph)
# or just re-run prepare.sh to refresh ./data/repos/* without touching the DB
```

Run outputs under `runs/` are gitignored.
