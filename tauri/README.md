# Noospheric

Desktop packaging of [Noospheric-Orrery](https://github.com/2389-research/Noospheric-Orrery) — install one app, get the whole adaptive knowledge-graph pipeline (FastAPI orchestrator, background worker, Next.js frontend) with no Docker and no dev toolchain.

> **New here?** Read [tauri.md](tauri.md) for the installation guide (assumes you know the Orrery project).

## How it works

A Tauri 2 app acts as a **supervisor**:

1. **Bundled resources** (`src-tauri/resources`, produced by `scripts/stage.sh`): a static `uv` binary, a `node` binary, the orchestrator/worker source + lockfiles (plus `orrery-relay` and `simmer-sdk`), and the frontend's Next.js standalone build.
2. **First run**: the app installs Python 3.12 and syncs both service venvs into the app data dir (`~/.local/share/ai.2389.noospheric` on Linux) using `uv` — one-time, ~500 MB download — then asks for an LLM backend (Anthropic API key / custom gateway, or Ollama for fully-local).
3. **Every run**: spawns orchestrator (`:8100`), worker, and the frontend (`:3100`), waits for health, and points the window at the frontend. Closing the window shuts everything down.

Data lives in `<app-data>/orrery-data/` (SQLite + documents + specs). Logs in `<app-data>/logs/`.

> The desktop app uses the same ports as the docker-compose stack (8100/3100) — run one or the other, not both. The app detects the conflict and tells you.

## Building

Requires: Rust (stable), Tauri system deps, network access.

```bash
npm install
npm run stage        # stages the parent Orrery checkout (or $ORRERY_DIR) into src-tauri/resources
npm run tauri dev    # develop
npm run tauri build  # produce installers (.deb / AppImage / etc.)
```

`scripts/stage.sh` builds the frontend with `NEXT_OUTPUT=standalone` (a small env-gated switch in Orrery's `next.config.ts`), downloads pinned `uv`/`node` binaries for the current platform, and copies service sources. Re-run it whenever Orrery changes. Flags: `--skip-frontend`, `--skip-runtimes`.

## Releasing

Push a `v*` tag (e.g. `v0.5.0`) — the `release-desktop.yml` workflow builds
the app on macOS CI, signs it with the 2389 Developer ID certificate,
notarizes it with Apple, and publishes a GitHub Release with the `.dmg`.
The app version comes from the tag; don't bump `tauri.conf.json` manually.

To test the pipeline without cutting a release, run the workflow manually
(`gh workflow run release-desktop.yml`) — it builds, signs, and notarizes,
then uploads the `.dmg` as a workflow artifact instead of a release.

See `docs/superpowers/specs/2026-08-04-desktop-release-workflow-design.md`
for the design (secrets, draft-then-flip publish, known consequences).

## Repo layout

```text
ui/                  Supervisor UI (plain HTML/JS: bootstrap progress, settings)
src-tauri/src/lib.rs Rust supervisor: provisioning, process spawn, health, shutdown
scripts/stage.sh     Staging script (run before dev/build)
docs/superpowers/specs/  Design docs
```

## Not yet done (v1 scope)

- Windows and Intel-macOS staging targets (stage.sh has the platform table; needs per-platform runs + signing)
- App icon (still the Tauri default)
- Migration helper for existing docker-compose data (copy `Noospheric-Orrery/data/*` into `<app-data>/orrery-data/`)
