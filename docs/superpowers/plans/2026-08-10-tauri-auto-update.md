# Tauri Desktop Auto-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Noospheric desktop app in-app auto-update so a shipped build can replace itself instead of stranding users on a broken version (the issue #52 scenario).

**Architecture:** Register the Tauri v2 updater plugin and drive it entirely from Rust behind two custom commands (`check_for_update`, `install_update`), because the bootstrap UI (`tauri/ui/`) is a bundler-less HTML/JS page that can only reach Rust through `invoke`/`listen`. The UI checks at launch (fail-open) and via a manual "Check for Updates…" window; a signed `latest.json` on GitHub Releases drives version comparison; minisign signs the update artifact in CI.

**Tech Stack:** Rust (`tauri` v2, `tauri-plugin-updater` v2), plain browser JS (no bundler), GitHub Actions (`tauri-apps/tauri-action@v0`), minisign signing.

**Design spec:** `docs/superpowers/specs/2026-08-10-tauri-auto-update-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Platform:** Apple-Silicon macOS only for v1 (matches today's single-arch release). No Intel/universal, no Windows/Linux.
- **Updater endpoint (verbatim):** `https://github.com/2389-research/Noospheric-Orrery/releases/latest/download/latest.json`
- **`AppHandle::restart(&self) -> !`** — it never returns; it is the diverging tail of `install_update`. Do **not** write a trailing `Ok(())` after it (unreachable-code warning). Zero new warnings is a hard rule.
- **Do not remove** the release workflow's "Set app version from tag" step — the updater's version comparison depends on the running app reporting the tag version.
- **Do not weaken** the "Verify bundled node entitlements" (`allow-jit`) gate — it still must block a bad build from publishing.
- **Signing keys are secrets:** the minisign private key + password live only in GitHub Actions secrets and (locally) outside the repo. Never commit them. Only the **public** key goes in `tauri.conf.json`.
- **New hand-written source files** start with two `ABOUTME:` comment lines.
- **One source of truth:** the launch card and the manual window share one `update.js`; no duplicated update logic or card markup/CSS.
- **Commits:** conventional, imperative. Never use `--no-verify` / `--no-hooks` / `--no-pre-commit-hook`.
- **User data** at `~/orrery-data/` (and the app data dir) is outside the bundle and is untouched by updates.

## File Structure

**Create:**
- `tauri/ui/update.js` — shared auto-update flow: injects card CSS once, builds the card DOM, runs check → prompt → install → progress. Exposes `window.OrreryUpdate.mountUpdateFlow` and `window.OrreryUpdate.withTimeout`. Used by both hosts.
- `tauri/ui/updates.html` — host page for the manual "Check for Updates…" window.
- `tauri/ui/updates.js` — thin host script: calls `mountUpdateFlow` in `"manual"` mode.

**Modify:**
- `tauri/src-tauri/Cargo.toml` — add `tauri-plugin-updater`.
- `tauri/src-tauri/tauri.conf.json` — `bundle.createUpdaterArtifacts` + `plugins.updater`.
- `tauri/src-tauri/src/lib.rs` — register plugin; add `UpdateInfo`/`UpdateProgress` structs, `check_for_update`/`install_update` commands, register them; add `open_updates_window`, the menu item, and the `on_menu_event` branch.
- `tauri/src-tauri/capabilities/default.json` — add `"updates"` to the `windows` list.
- `tauri/ui/index.html` — load `update.js` before `index.js`.
- `tauri/ui/index.js` — run the launch-time check at the top of `init()`.
- `.github/workflows/release-desktop.yml` — `includeUpdaterJson: true` + minisign signing env.

## A note on testing (read before starting)

This feature is mostly thin adapters over a network + filesystem + process-restart plugin, plus browser glue. There is very little fixture-free pure logic to unit-test honestly:

- The Rust commands are passthroughs to `tauri-plugin-updater`; the `Update` type is plugin-owned (constructing one in a test is fragile and may be `#[non_exhaustive]`), and `check()`/`download_and_install()`/`restart()` need a real network + a real signed artifact. Unit-testing them would mean testing mocks — which this project forbids.
- The one behaviour with a real, nasty regression mode is **fail-open** (a hung update check must never block launch). That lives in the pure `withTimeout` helper and is covered by the manual e2e checklist (blackhole endpoint), because `tauri/ui/` has no JS test runner and adding one for six lines fights the UI's deliberate zero-dependency design.

So per-task verification is: **`cargo build` + `cargo clippy` (zero warnings) + existing `cargo test` stays green** for Rust, **loads-without-console-errors** smoke for JS, and a **real signed test release** for the genuine end-to-end proof (Task 8).

**This means v1 ships without new unit tests, by deliberate choice.** Per Harper's rule, skipping a test *type* is his call — Task 8 exists to make the e2e coverage explicit, and this note surfaces the decision rather than burying it. If Harper wants mock-based Rust unit tests anyway, add them; the author's recommendation is not to.

---

### Task 1: Register the updater plugin + config + keypair

**Files:**
- Modify: `tauri/src-tauri/Cargo.toml`
- Modify: `tauri/src-tauri/tauri.conf.json`
- Modify: `tauri/src-tauri/src/lib.rs:665-667` (the builder chain, right after the opener plugin)

**Interfaces:**
- Produces: a registered updater plugin (enables `UpdaterExt::updater()` in Task 2); `plugins.updater.pubkey`/`endpoints` config; `bundle.createUpdaterArtifacts: true`.

- [ ] **Step 1: Generate the minisign keypair (one-time, local)**

From `tauri/`:

```bash
npm ci
npm run tauri signer generate -- -w "$HOME/.tauri/noospheric-updater.key"
```

This writes `~/.tauri/noospheric-updater.key` (private) and `~/.tauri/noospheric-updater.key.pub` (public), prompting for a password. Keep the private key and password OUT of the repo. Print the public key to paste next:

```bash
cat "$HOME/.tauri/noospheric-updater.key.pub"
```

- [ ] **Step 2: Add the Cargo dependency**

In `tauri/src-tauri/Cargo.toml`, under `[dependencies]`, add:

```toml
tauri-plugin-updater = "2"
```

- [ ] **Step 3: Register the plugin**

In `tauri/src-tauri/src/lib.rs`, in `run()`, add the plugin to the builder chain immediately after the existing opener plugin line:

```rust
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Supervisor::default())
```

(Registered unconditionally: this app targets desktop only, so the `#[cfg(desktop)]` guard mentioned in the spec would only force an awkward break in the fluent chain for no real benefit. Noted as a deliberate, minor deviation from the spec.)

- [ ] **Step 4: Configure the bundle + updater in `tauri.conf.json`**

Add `createUpdaterArtifacts` to the existing `bundle` object and a new top-level `plugins` object. Paste the public key from Step 1 into `pubkey` (single line, verbatim):

```jsonc
  "bundle": {
    "active": true,
    "createUpdaterArtifacts": true,
    "targets": "all",
    "resources": { "resources": "resources" },
    "icon": [ /* unchanged */ ]
  },
  "plugins": {
    "updater": {
      "pubkey": "PASTE_THE_CONTENTS_OF_noospheric-updater.key.pub_HERE",
      "endpoints": [
        "https://github.com/2389-research/Noospheric-Orrery/releases/latest/download/latest.json"
      ]
    }
  }
```

- [ ] **Step 5: Verify it compiles**

Run:

```bash
cd tauri/src-tauri && cargo build 2>&1 | tail -20
```

Expected: builds. `tauri::generate_context!()` parses `tauri.conf.json` at compile time and validates the `pubkey`; a missing/malformed key fails here — that is the check that the key was pasted correctly.

- [ ] **Step 6: Confirm existing tests still pass and clippy is clean**

```bash
cd tauri/src-tauri && cargo test 2>&1 | tail -20 && cargo clippy --all-targets 2>&1 | tail -20
```

Expected: 7 existing tests pass; no new warnings.

- [ ] **Step 7: Commit** (the `.pub` is safe to reference; the private key is not in the repo)

```bash
git add tauri/src-tauri/Cargo.toml tauri/src-tauri/Cargo.lock tauri/src-tauri/tauri.conf.json tauri/src-tauri/src/lib.rs
git commit -m "feat(tauri): register updater plugin and updater config"
```

---

### Task 2: `check_for_update` and `install_update` commands

**Files:**
- Modify: `tauri/src-tauri/src/lib.rs` (add structs + commands near the other `#[tauri::command]`s, e.g. after `get_log_buffer`; add both to the handler list at `lib.rs:668-675`)

**Interfaces:**
- Consumes: the registered updater plugin (Task 1); `use tauri::{Emitter, Manager, State};` already imported at `lib.rs:14`.
- Produces:
  - `check_for_update() -> Result<Option<UpdateInfo>, String>` where `UpdateInfo { version: String, current_version: String, notes: Option<String> }`.
  - `install_update() -> Result<(), String>` — emits `update-progress` with `UpdateProgress { downloaded: usize, total: Option<u64> }` during download, then restarts the app.
  - Both invoked by `update.js` (Task 4).

- [ ] **Step 1: Add the `UpdaterExt` import**

At the top of `lib.rs`, with the other `use` lines:

```rust
use tauri_plugin_updater::UpdaterExt;
```

- [ ] **Step 2: Add the serializable structs**

Place near the other `#[derive(Serialize)]` structs (e.g. after `Status`):

```rust
/// Update metadata the webview needs to render the prompt. The raw plugin
/// `Update` stays in Rust; the webview only sees these three fields.
#[derive(Serialize)]
struct UpdateInfo {
    version: String,
    current_version: String,
    notes: Option<String>,
}

/// Download progress streamed to the webview during install.
#[derive(Serialize, Clone)]
struct UpdateProgress {
    downloaded: usize,
    total: Option<u64>,
}
```

- [ ] **Step 3: Add `check_for_update`**

```rust
/// Ask the update endpoint whether a newer version exists. `Ok(None)` means
/// up to date; `Err` means the check itself failed (offline, endpoint down)
/// — the caller treats that as "proceed on the current version".
#[tauri::command]
async fn check_for_update(app: tauri::AppHandle) -> Result<Option<UpdateInfo>, String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    let maybe_update = updater.check().await.map_err(|e| e.to_string())?;
    Ok(maybe_update.map(|update| UpdateInfo {
        version: update.version,
        current_version: update.current_version,
        notes: update.body,
    }))
}
```

- [ ] **Step 4: Add `install_update`**

```rust
/// Download and install the pending update, streaming progress, then restart
/// onto the new version. Re-checks so it doesn't have to hold the non-'static
/// `Update` across the earlier IPC call; a `None` here means the release moved
/// between check and confirm — a harmless no-op.
#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    let Some(update) = updater.check().await.map_err(|e| e.to_string())? else {
        return Ok(());
    };
    let app_progress = app.clone();
    let mut downloaded: usize = 0;
    update
        .download_and_install(
            move |chunk_length, content_length| {
                downloaded += chunk_length;
                let _ = app_progress.emit(
                    "update-progress",
                    UpdateProgress { downloaded, total: content_length },
                );
            },
            || {},
        )
        .await
        .map_err(|e| e.to_string())?;
    app.restart();
}
```

- [ ] **Step 5: Register both commands**

In `tauri::generate_handler![...]` (`lib.rs:668`), add the two commands:

```rust
        .invoke_handler(tauri::generate_handler![
            get_status,
            get_settings,
            save_settings,
            bootstrap,
            launch,
            get_log_buffer,
            check_for_update,
            install_update
        ])
```

- [ ] **Step 6: Verify build, clippy, tests**

```bash
cd tauri/src-tauri && cargo build 2>&1 | tail -20 && cargo clippy --all-targets 2>&1 | tail -20 && cargo test 2>&1 | tail -20
```

Expected: builds, no new warnings, 7 existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add tauri/src-tauri/src/lib.rs
git commit -m "feat(tauri): add check_for_update and install_update commands"
```

---

### Task 3: Manual-check window plumbing (menu, window, capability)

**Files:**
- Modify: `tauri/src-tauri/src/lib.rs` (menu item in `setup()` at ~`lib.rs:685-693`; `on_menu_event` at ~`lib.rs:744-750`; add `open_updates_window` near `open_logs_window` at ~`lib.rs:596-610`)
- Modify: `tauri/src-tauri/capabilities/default.json`

**Interfaces:**
- Consumes: `WebviewWindowBuilder`/`WebviewUrl` pattern from `open_logs_window`.
- Produces: a `"updates"` webview window loading `updates.html`, opened from a "Check for Updates…" menu item. The `"updates"` window is authorized to call commands/listen for events via the default capability.

- [ ] **Step 1: Add `open_updates_window`**

Next to `open_logs_window` in `lib.rs`:

```rust
/// Open (or focus) the software-update window — the manual "Check for
/// Updates…" entry point. Runs the same update flow as launch, in its own
/// window because after launch the main window has navigated to the frontend.
fn open_updates_window(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("updates") {
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }
    let _ = tauri::WebviewWindowBuilder::new(
        app,
        "updates",
        tauri::WebviewUrl::App("updates.html".into()),
    )
    .title("Noospheric — Software Update")
    .inner_size(520.0, 420.0)
    .build();
}
```

- [ ] **Step 2: Add the menu item**

In `setup()`, alongside `logs_item` and `settings_item`:

```rust
            let updates_item =
                MenuItem::with_id(app, "check-updates", "Check for Updates…", true, None::<&str>)?;
```

Add it to the submenu items (put it before `quit`):

```rust
            let submenu = Submenu::with_items(
                app,
                "Noospheric",
                true,
                &[&logs_item, &settings_item, &updates_item, &quit],
            )?;
```

- [ ] **Step 3: Handle the menu event**

In `on_menu_event`, add a branch:

```rust
        .on_menu_event(|app, event| {
            if event.id() == "view-logs" {
                open_logs_window(app);
            } else if event.id() == "change-settings" {
                reopen_settings(app);
            } else if event.id() == "check-updates" {
                open_updates_window(app);
            }
        })
```

- [ ] **Step 4: Authorize the new window in the capability**

In `tauri/src-tauri/capabilities/default.json`, add `"updates"` to `windows` (permissions unchanged):

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Capability for the main, logs, and updates windows",
  "windows": ["main", "logs", "updates"],
  "permissions": [
    "core:default",
    "opener:default"
  ]
}
```

(Correction to the spec, which said "no capability changes": the launch check runs in the already-authorized `main` window, but the new `updates` window must be added to this list or its JS can't `invoke`/`listen`. This is a windows-list change, not a new permission.)

- [ ] **Step 5: Verify build/clippy**

```bash
cd tauri/src-tauri && cargo build 2>&1 | tail -20 && cargo clippy --all-targets 2>&1 | tail -20
```

Expected: builds, no new warnings. (The window renders once `updates.html` exists in Task 5; the menu item is wired now.)

- [ ] **Step 6: Commit**

```bash
git add tauri/src-tauri/src/lib.rs tauri/src-tauri/capabilities/default.json
git commit -m "feat(tauri): add Check for Updates menu item and updates window"
```

---

### Task 4: Shared update flow (`update.js`)

**Files:**
- Create: `tauri/ui/update.js`

**Interfaces:**
- Consumes: `check_for_update`, `install_update` commands (Task 2); `update-progress` event (Task 2); `window.__TAURI__.core.invoke`, `window.__TAURI__.event.listen`.
- Produces (globals, no bundler):
  - `window.OrreryUpdate.withTimeout(promise, ms, fallback) -> Promise` — resolves to `fallback` if `promise` doesn't settle in `ms` (fail-open).
  - `window.OrreryUpdate.mountUpdateFlow({ container, mode, onDone }) -> Promise<void>` — `mode` is `"launch"` (silent when current/timed-out/errored → calls `onDone`) or `"manual"` (announces "up to date" and shows errors). Shows the prompt + progress when an update exists; on "Install" it calls `install_update` (which restarts the app, so `onDone` is not called on that path).

- [ ] **Step 1: Write `update.js`**

```javascript
// ABOUTME: Shared desktop auto-update flow for the launch screen and the
// ABOUTME: manual "Check for Updates…" window. Browser globals only, no bundler.
const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

// Fail-open: resolve to `fallback` if `promise` doesn't settle within `ms`.
// A slow or hung update check must never keep the user out of the app.
function withTimeout(promise, ms, fallback) {
  return Promise.race([
    promise,
    new Promise((resolve) => setTimeout(() => resolve(fallback), ms)),
  ]);
}

// Inject the card CSS once, so both hosts render an identical card from one
// source (no duplicated styles across index.html and updates.html).
function ensureStyle() {
  if (document.getElementById("orrery-update-style")) return;
  const el = document.createElement("style");
  el.id = "orrery-update-style";
  el.textContent = `
    .ou-card { background:#141a2e; border:1px solid #232c4a; border-radius:12px;
      padding:20px; color:#dde3f0; font:15px/1.5 system-ui, sans-serif;
      width:min(520px,92vw); margin:0 auto; }
    .ou-title { font-size:18px; margin:0 0 8px; }
    .ou-notes { color:#8b94ad; font-size:13px; white-space:pre-wrap;
      max-height:180px; overflow-y:auto; margin:0 0 16px; }
    .ou-row { display:flex; gap:8px; }
    .ou-btn { padding:10px 18px; border-radius:8px; border:0; background:#5b6cff;
      color:#fff; font-weight:600; cursor:pointer; }
    .ou-btn.ghost { background:transparent; border:1px solid #2c3760; color:#aab3cc; }
    .ou-btn:disabled { opacity:.5; cursor:default; }
    .ou-bar { height:8px; background:#05070f; border-radius:6px; overflow:hidden;
      margin-top:14px; }
    .ou-bar > i { display:block; height:100%; width:0; background:#5b6cff;
      transition:width .15s linear; }
    .ou-status { color:#8b94ad; font-size:12px; margin-top:8px; }
    .ou-error { color:#ff8484; font-size:13px; white-space:pre-wrap; }
  `;
  document.head.appendChild(el);
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

async function runInstall(card, statusEl) {
  // Swap the buttons for a progress bar, then install. install_update restarts
  // the app on success, so control does not return here on the happy path.
  const bar = el("div", "ou-bar");
  const fill = el("i");
  bar.appendChild(fill);
  card.appendChild(bar);
  statusEl.textContent = "Downloading…";
  const un = await listen("update-progress", (e) => {
    const { downloaded, total } = e.payload;
    if (total) {
      fill.style.width = `${Math.min(100, Math.round((downloaded / total) * 100))}%`;
      statusEl.textContent = `Downloading… ${Math.round(downloaded / 1e6)} MB`;
    } else {
      statusEl.textContent = `Downloading… ${Math.round(downloaded / 1e6)} MB`;
    }
  });
  try {
    await invoke("install_update");
    statusEl.textContent = "Installing… the app will restart.";
  } catch (err) {
    un();
    fill.style.background = "#ff8484";
    statusEl.className = "ou-status ou-error";
    statusEl.textContent = `Update failed: ${String(err)}`;
  }
}

// mode: "launch" | "manual"
async function mountUpdateFlow({ container, mode, onDone }) {
  ensureStyle();
  const done = typeof onDone === "function" ? onDone : () => {};

  let info;
  try {
    info = await withTimeout(invoke("check_for_update"), 5000, { __timedOut: true });
  } catch (err) {
    info = { __error: String(err) };
  }

  // Fail-open on timeout: never block launch on a slow/hung check.
  if (info && info.__timedOut) {
    done();
    return;
  }

  const card = el("div", "ou-card");

  if (info && info.__error) {
    if (mode !== "manual") {
      done();
      return;
    }
    card.appendChild(el("h2", "ou-title", "Couldn't check for updates"));
    card.appendChild(el("p", "ou-error", info.__error));
    container.appendChild(card);
    return;
  }

  if (!info) {
    if (mode !== "manual") {
      done();
      return;
    }
    card.appendChild(el("h2", "ou-title", "You're up to date"));
    card.appendChild(el("p", "ou-notes", "You can close this window."));
    container.appendChild(card);
    return;
  }

  // An update is available.
  card.appendChild(el("h2", "ou-title", `Version ${info.version} is available`));
  if (info.notes) card.appendChild(el("p", "ou-notes", info.notes));
  const status = el("div", "ou-status");
  const row = el("div", "ou-row");
  const install = el("button", "ou-btn", "Install & Restart");
  const later = el("button", "ou-btn ghost", mode === "manual" ? "Close" : "Not now");
  row.appendChild(install);
  row.appendChild(later);
  card.appendChild(row);
  card.appendChild(status);
  container.appendChild(card);

  later.addEventListener("click", () => {
    card.remove();
    done();
  });
  install.addEventListener("click", () => {
    install.disabled = true;
    later.disabled = true;
    runInstall(card, status);
  });
}

window.OrreryUpdate = { mountUpdateFlow, withTimeout };
```

- [ ] **Step 2: Syntax smoke check**

```bash
node --check tauri/ui/update.js
```

Expected: no output (valid JS). (This only parses the file; `window.__TAURI__` is a runtime global, not exercised here.)

- [ ] **Step 3: Commit**

```bash
git add tauri/ui/update.js
git commit -m "feat(tauri-ui): shared auto-update flow"
```

---

### Task 5: Manual update window host (`updates.html` + `updates.js`)

**Files:**
- Create: `tauri/ui/updates.html`
- Create: `tauri/ui/updates.js`

**Interfaces:**
- Consumes: `window.OrreryUpdate.mountUpdateFlow` (Task 4).
- Produces: the page loaded by the `"updates"` window (Task 3).

- [ ] **Step 1: Write `updates.html`**

```html
<!doctype html>
<!-- ABOUTME: Host page for the manual "Check for Updates…" window. -->
<!-- ABOUTME: Delegates all logic to the shared update.js flow. -->
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Software Update</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; }
  body { background:#0b0e1a; min-height:100vh; display:grid; place-items:center; padding:20px; }
</style>
</head>
<body>
  <main id="update-root"></main>
  <script src="update.js"></script>
  <script src="updates.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `updates.js`**

```javascript
// ABOUTME: Thin host for the manual update window — runs the shared update
// ABOUTME: flow in "manual" mode so it announces "up to date" and errors.
window.OrreryUpdate.mountUpdateFlow({
  container: document.getElementById("update-root"),
  mode: "manual",
  onDone: () => {},
});
```

- [ ] **Step 3: Syntax smoke check**

```bash
node --check tauri/ui/updates.js
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add tauri/ui/updates.html tauri/ui/updates.js
git commit -m "feat(tauri-ui): manual Check for Updates window"
```

---

### Task 6: Launch-time check (`index.html` + `index.js`)

**Files:**
- Modify: `tauri/ui/index.html:83` (add the `update.js` script before `index.js`)
- Modify: `tauri/ui/index.js:116-131` (the `init()` IIFE)

**Interfaces:**
- Consumes: `window.OrreryUpdate.mountUpdateFlow` (Task 4).
- Produces: a fail-open update prompt before any service starts.

- [ ] **Step 1: Load `update.js` before `index.js`**

In `index.html`, change the script block at the bottom to:

```html
<script src="update.js"></script>
<script src="index.js"></script>
```

- [ ] **Step 2: Run the check at the top of `init()`**

In `index.js`, replace the `init()` IIFE with a version that checks for an update first. The update flow calls `onDone` when there's no update, a timeout, or a non-manual error, and on "Not now"; when the user installs, the app restarts (so the rest of `init` never runs, which is correct):

```javascript
(async function init() {
  try {
    // Offer an update before touching services — the only safe window to
    // swap the bundle. Fail-open is built into mountUpdateFlow (5s timeout).
    await new Promise((resolve) =>
      window.OrreryUpdate.mountUpdateFlow({
        container: document.querySelector("main"),
        mode: "launch",
        onDone: resolve,
      })
    );
    const forceSettings = new URLSearchParams(window.location.search).get("settings") === "1";
    const status = await invoke("get_status");
    if (!status.has_settings || forceSettings) {
      const prefill = forceSettings
        ? await invoke("get_settings").catch(() => null)
        : null;
      showSettings(prefill);
    } else {
      start();
    }
  } catch (e) {
    fail(e);
  }
})();
```

- [ ] **Step 3: Syntax smoke check**

```bash
node --check tauri/ui/index.js
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add tauri/ui/index.html tauri/ui/index.js
git commit -m "feat(tauri-ui): check for updates at launch before starting services"
```

---

### Task 7: Wire updater artifacts + signing into the release workflow

**Files:**
- Modify: `.github/workflows/release-desktop.yml:164-180` (the `tauri-apps/tauri-action@v0` step)

**Interfaces:**
- Consumes: GitHub secrets `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (added by Harper in Task 8).
- Produces: `latest.json` + signed `.app.tar.gz` + `.sig` uploaded to each published release.

- [ ] **Step 1: Add the signing env and flip `includeUpdaterJson`**

In the "Build, sign, notarize" step, add the two signing vars to `env` and change the one `with` line:

```yaml
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
          APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}
          APPLE_SIGNING_IDENTITY: ${{ secrets.APPLE_SIGNING_IDENTITY }}
          APPLE_API_ISSUER: ${{ secrets.APPLE_API_ISSUER }}
          APPLE_API_KEY: ${{ secrets.APPLE_API_KEY }}
          TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
          TAURI_SIGNING_PRIVATE_KEY_PASSWORD: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}
          # APPLE_API_KEY_PATH and KEYCHAIN_PASSWORD arrive via GITHUB_ENV above
        with:
          projectPath: tauri
          tagName: ${{ github.ref_type == 'tag' && github.ref_name || '' }}
          releaseName: ${{ github.ref_type == 'tag' && format('Noospheric {0}', github.ref_name) || '' }}
          releaseDraft: true
          prerelease: ${{ github.ref_type == 'tag' && contains(github.ref_name, '-') }}
          includeUpdaterJson: true
```

- [ ] **Step 2: Validate the workflow YAML**

```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release-desktop.yml')); print('yaml ok')"
```

Expected: `yaml ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release-desktop.yml
git commit -m "ci: publish signed updater artifacts (latest.json) on release"
```

---

### Task 8: Secrets setup + end-to-end verification

**Files:** none (human setup + manual verification). This task is the feature's real test.

**Interfaces:**
- Consumes: everything above; the minisign private key + password from Task 1.

- [ ] **Step 1: Add the GitHub Actions secrets (Harper)**

In the repo settings → Secrets and variables → Actions, add:
- `TAURI_SIGNING_PRIVATE_KEY` — the **contents** of `~/.tauri/noospheric-updater.key`.
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` — the password chosen in Task 1.

- [ ] **Step 2: Open the PR and merge to main** once Tasks 1–7 are green in CI.

- [ ] **Step 3: Cut a baseline release** — tag `vX.Y.Z` (the first build carrying the updater). CI must produce a **published** release whose assets include `latest.json`, `Noospheric_*.app.tar.gz`, and `*.app.tar.gz.sig`.

Verify the manifest is reachable and well-formed:

```bash
curl -sL https://github.com/2389-research/Noospheric-Orrery/releases/latest/download/latest.json | jq '{version, platforms: (.platforms | keys)}'
```

Expected: the tagged `version` and a `darwin-aarch64` platform key.

- [ ] **Step 4: Install the baseline** DMG on an Apple-Silicon Mac and confirm it launches normally (no update offered — it is the latest).

- [ ] **Step 5: Cut the next release** `vX.Y.(Z+1)` with a trivial visible change.

- [ ] **Step 6: Verify the launch path** — relaunch the **baseline** install. Expected: the update card appears before services start; "Install & Restart" shows download progress, the app restarts on the new version, and (because the bundled lockfiles' fingerprint is unchanged) it does not needlessly re-provision.

- [ ] **Step 7: Verify the manual path** — on the now-current install, menu → "Check for Updates…" opens the window and shows "You're up to date". (To see the available-update branch, run it on the baseline before installing.)

- [ ] **Step 8: Verify fail-open** — with the baseline (out-of-date) install, block the endpoint (e.g. add `127.0.0.1 github.com` to `/etc/hosts`, or pull the network) and launch. Expected: the app starts normally within ~5s; it does **not** hang on the update check. Restore `/etc/hosts` afterwards.

---

## Self-Review

**Spec coverage:**
- Plugin + config → Task 1. ✅
- Two Rust commands (`check_for_update`, `install_update`) → Task 2. ✅
- Launch-time fail-open check → Task 6 (+ `withTimeout` in Task 4). ✅
- Manual "Check for Updates…" window → Tasks 3, 5. ✅
- Shared `update.js` (one source of truth) → Task 4. ✅
- `createUpdaterArtifacts` + `plugins.updater.{pubkey,endpoints}` → Task 1. ✅
- CI `includeUpdaterJson: true` + `TAURI_SIGNING_*` → Task 7. ✅
- Endpoint / prerelease behavior / version-from-tag → Global Constraints + Task 7 (workflow unchanged there). ✅
- Signing keys & secrets one-time setup → Task 1 (generate) + Task 8 (secrets). ✅
- Failure handling (offline/timeout/download error/race) → Task 2 (`Err`, re-check) + Task 4 (fail-open, error card). ✅
- Testing (Rust build/clippy/existing tests; e2e) → "A note on testing" + per-task steps + Task 8. ✅
- YAGNI (no delta/silent/multi-arch/non-macOS) → Global Constraints. ✅
- **Correction found:** spec said "no capability changes"; the manual window requires adding `"updates"` to the capability `windows` list → captured in Task 3 with an explicit note.

**Placeholder scan:** the only literal placeholder is `PASTE_THE_CONTENTS_OF_...` in Task 1 — a genuine generated-secret value with the exact command that produces it, not a logic gap. No TBD/TODO/"handle edge cases".

**Type consistency:** `UpdateInfo { version, current_version, notes }` and `UpdateProgress { downloaded, total }` are defined in Task 2 and consumed with the same field names in Task 4's JS (`info.version`, `info.notes`, `e.payload.downloaded`, `e.payload.total`). Command names `check_for_update` / `install_update` and event name `update-progress` match across Rust (Task 2) and JS (Task 4). Window label `"updates"` matches across Task 3 (`open_updates_window`, capability) and Task 5 (`updates.html`). `window.OrreryUpdate.mountUpdateFlow` signature matches across Tasks 4, 5, 6.
