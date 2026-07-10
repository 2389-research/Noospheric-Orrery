# Noospheric: Tauri desktop packaging of Noospheric-Orrery

**Date:** 2026-07-02
**Status:** Approved by default (user AFK — recommended options chosen; revisit if user objects)

## Goal

Package Noospheric-Orrery (FastAPI orchestrator + Python worker + Next.js frontend,
currently docker-compose) as a desktop app people can install and run without Docker
or a dev toolchain. First target: Linux. macOS/Windows later via the same mechanism.

## Decisions taken (user was AFK; recorded for review)

1. **Backend runtime: bundled `uv` + first-run provisioning**, not PyInstaller.
   The Python services depend on torch (CPU), faiss-cpu, umap-learn, and
   sentence-transformers — a stack that freezes badly under PyInstaller and would
   produce multi-GB binaries per platform. Instead the app ships the service
   *source* plus lockfiles and a single static `uv` binary; on first run, uv
   installs Python 3.12 and `uv sync --frozen`s the two venvs into the app data
   dir. One-time network download (~500MB of wheels), with a progress screen.
2. **Frontend: Next.js standalone build + bundled Node runtime.** The frontend
   uses runtime-dynamic routes (`/n/[noosphereId]/…`) with no
   `generateStaticParams`, so `output: "export"` is not viable without deep
   surgery in the Orrery repo. We build `output: "standalone"` at package time and
   ship a Node binary (~55MB) to run it. The existing `/api/:path*` rewrite proxy
   keeps working unchanged.
3. **LLM backends at launch: Anthropic API key + Ollama.** A first-run settings
   screen collects either an `sk-ant-…` key or an Ollama URL + model names.
   Bedrock remains possible via a hand-edited env file (power users).
4. **Platforms: Linux first** (dev machine); the design avoids anything
   platform-locked — uv/node binaries are per-platform downloads in the staging
   script.

## Architecture

```
Tauri app (Rust supervisor + tiny static supervisor UI)
│
├─ resources/ (bundled at package time by scripts/stage.sh)
│   ├─ bin/uv                        static uv binary
│   ├─ bin/node                      node runtime
│   ├─ services/orchestrator/        source + pyproject + uv.lock
│   ├─ services/worker/              source + pyproject + uv.lock
│   ├─ services/packages/orrery-relay/
│   ├─ services/simmer-sdk/          cloned dep of worker
│   └─ frontend/                     .next/standalone build (server.js, static, public)
│
└─ app data dir (~/.local/share/ai.2389.noospheric/)
    ├─ runtime/python/               uv-managed CPython 3.12
    ├─ runtime/venvs/{orchestrator,worker}/
    ├─ orrery-data/                  SQLite DB, documents, specs (ORRERY_DATA_DIR)
    ├─ settings.json                 backend choice, API key, Ollama config
    └─ logs/{orchestrator,worker,frontend}.log
```

### Runtime flow

1. Window opens on the bundled **supervisor UI** (plain HTML/JS, no framework).
2. Rust checks provisioning state (`runtime/.provisioned` stamp matching a hash of
   the bundled lockfiles). If stale/missing → **bootstrap screen**: run
   `uv python install 3.12`, then `uv sync --frozen` per service, streaming
   progress lines to the UI via Tauri events.
3. If `settings.json` missing → **settings screen** (Anthropic key or Ollama).
4. **Launch**: spawn three children with env derived from settings:
   - orchestrator: `<venv>/bin/python -m uvicorn src.main:app --port 8100`
   - worker: `<venv>/bin/python -m src.main`
   - frontend: `node server.js` (standalone) with `PORT=3100`,
     `BACKEND_URL=http://127.0.0.1:8100`, `HOSTNAME=127.0.0.1`
5. Poll `http://127.0.0.1:8100/stats` and `:3100` until healthy, then navigate the
   window to `http://127.0.0.1:3100`.
6. On window close / app exit: kill all children (process-group kill so uvicorn
   workers die too). A `tray`-less v1: closing the window quits the app.
7. Settings reachable later via a `noospheric://settings` — v1: keyboard-free
   approach, small "gear" injected? No — v1 keeps it simple: relaunching with the
   env broken shows settings again; plus a Tauri menu item "Backend Settings"
   that navigates back to the supervisor UI.

### Error handling

- Any child exiting during startup → supervisor UI shows the tail of its log file.
- Ports 8100/3100 busy → fail fast with a clear message (v1 uses fixed ports).
- Bootstrap failure (offline, disk) → retry button; nothing partial is marked
  provisioned (stamp written only on success).

### Testing

- Rust unit tests for settings serialization and provisioning-stamp logic.
- Manual E2E on Linux via `cargo tauri dev` and a real `.deb`/AppImage build:
  fresh data dir → bootstrap → settings → upload a doc → entities appear.

## Out of scope (v1)

- Code signing / notarization, auto-update, macOS/Windows builds (mechanism is
  ready; binaries per platform added to stage script later).
- Bundling Ollama or models; user installs Ollama themselves.
- Migrating existing docker-compose users' data (they can copy `./data` into the
  app data dir manually).
