# Installing the Tauri Desktop App (Orrery)

This is the installation guide for the **desktop packaging** of orrery.
It assumes you've already read the project overview and setup notes in
[orrery's CLAUDE.md](https://github.com/2389-research/orrery/blob/main/CLAUDE.md)
— what the pipeline is, its three services, the LLM backends, and where data
lives. This doc only covers building and running the Tauri app that bundles all
of that into a single desktop application (no Docker needed).

## Prerequisites

- **Rust** (stable) — `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
- **Node.js ≥ 20** — check with `node --version`
- **Tauri system libraries** (Linux):

  ```bash
  sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file \
    libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
  ```

  Other distros / macOS: https://tauri.app/start/prerequisites/

## Install

The Tauri app lives in this repo's `tauri/` subfolder, one level below
orrery itself — the stage script resolves the Orrery checkout as
its own parent directory by default (override with `ORRERY_DIR` if staging
from a different Orrery checkout):

```bash
git clone https://github.com/2389-research/orrery.git
cd orrery/tauri
npm install
npm run stage        # stages services, frontend build, uv/node binaries into src-tauri/resources
npm run tauri dev    # compile and open the app
```

For distributable installers (.deb / AppImage) instead of dev mode:

```bash
npm run tauri build  # output in src-tauri/target/release/bundle/
```

## First launch

The app asks for an LLM backend (same options as the `.env` config you know
from the Orrery repo — Anthropic API/gateway or Ollama), then provisions the
Python environments with the bundled `uv` (one-time, ~500 MB). After that it
starts the orchestrator (:8100), worker, and frontend (:3100) and switches the
window to the Orrery UI.

Note the ports: the desktop app and the docker-compose stack can't run at the
same time.

## Where things go

- Settings: `~/.local/share/ai.2389.noospheric/settings.json`
  (use the app's **Orrery → Change Settings…** menu item to reconfigure
  the backend/API key without reinstalling — it restarts the services with
  the new settings automatically)
- Data (the equivalent of the compose stack's `./data/`):
  `~/.local/share/ai.2389.noospheric/orrery-data/`
- Logs: `~/.local/share/ai.2389.noospheric/logs/`, or press `Ctrl+L` in the
  app for a live view

## Troubleshooting

| Problem | Fix |
|---|---|
| `npm run stage`: "orrery not found" | Run from `orrery/tauri` — or set `ORRERY_DIR=/path/to/orrery npm run stage` if staging from elsewhere |
| "Port 8100/3100 already in use" | The docker-compose stack (or another copy) is running — stop it first |
| First-run setup fails partway | Network hiccup — click **Retry**, it resumes from where it stopped |
| Uploads fail after launch | `Ctrl+L`, look for red lines — usually a bad/empty API key |
| Clean slate | Quit, `rm -rf ~/.local/share/ai.2389.noospheric`, relaunch |
