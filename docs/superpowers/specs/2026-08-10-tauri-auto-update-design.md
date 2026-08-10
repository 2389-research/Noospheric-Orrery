# Tauri Desktop Auto-Update (v1 Design)

**Date:** 2026-08-10 · **Status:** Design · **Author:** Nomzor
**Branch (intended):** `feat/tauri-auto-update`

## Context

The Noospheric desktop app ships as a signed, notarized macOS bundle (see
`.github/workflows/release-desktop.yml`). Today there is **no update path**: once a user installs a
build, it is frozen. Issue #52 is the cautionary tale — a broken build (V8 SIGTRAP from a stripped
`allow-jit` entitlement) can only be replaced by the user noticing, finding the repo, and
re-downloading a DMG by hand. That is exactly the failure an auto-updater exists to close.

This design adds in-app auto-update using the **Tauri v2 updater plugin** (`tauri-plugin-updater`), a
signed `latest.json` manifest served from GitHub Releases, and minisign artifact signing wired into the
existing release workflow. The whole app bundle is replaced on update, so a bad `node`, frontend, or
service is swapped wholesale on the next launch — the #52 scenario becomes self-healing going forward.

## Decisions (settled)

1. **Mechanism: Tauri updater plugin**, not the literal Sparkle framework. Sparkle is macOS-only with no
   first-class Tauri integration; the Tauri updater is the idiomatic path and cross-platform if we ever
   want it.
2. **UX: prompt at launch, before services boot**, plus a manual "Check for Updates…". The app supervises
   long-running services (orchestrator/worker/frontend); the only safe window to swap the bundle is at
   startup when nothing is running. Silent auto-install and mid-session updates are rejected for a
   supervisor app.
3. **Architecture: Rust-driven**, not JS-plugin-driven. The launch UI (`tauri/ui/`) is a bundler-less
   HTML/JS page that can only talk to Rust via `invoke`/`listen` — it cannot `import` the JS updater
   plugin. So the updater runs entirely in Rust behind two custom commands; the UI just prompts and shows
   progress. This also keeps signature verification in Rust and adds zero new JS dependencies.

### Why not the alternatives (architecture fork)

- **JS updater plugin in the webview** — `tauri/ui/` has no bundler and no `import`. Depends on plugin
  globals we can't guarantee are injected. Rejected on a hard fact.
- **All native OS dialogs** — native message dialogs can't show a download progress bar; the bundle is
  ~100 MB, so the app would look hung for several seconds. Rejected on UX.

## What ships in v1 (scope)

1. **Plugin + config** — register `tauri-plugin-updater`; set `bundle.createUpdaterArtifacts: true` and
   `plugins.updater.{pubkey,endpoints}` in `tauri.conf.json`.
2. **Two Rust commands** — `check_for_update` and `install_update` (details below).
3. **Launch-time check** — `index.js` checks at startup, fail-open, and shows a styled update card if an
   update exists.
4. **Manual check** — a "Check for Updates…" menu item opens a small dedicated `updates` window running
   the same update flow.
5. **Shared update flow** — one `update.js` owns the check → prompt → install → progress logic and DOM,
   used by both entry points (one source of truth).
6. **Release wiring** — `includeUpdaterJson: true` and minisign signing env in the release workflow, so
   each release publishes `latest.json` + the signed `.app.tar.gz`.

## Non-goals (explicit YAGNI)

- **No delta updates**, no background/silent auto-install, no staged rollouts.
- **No multi-arch / non-macOS.** v1 tracks whatever the release builds today: **Apple-Silicon macOS
  only**. Intel and Windows/Linux are out of scope until the build matrix grows.
- **No new re-provisioning logic.** Updating swaps the bundled lockfiles; the existing
  `lockfiles_fingerprint` check already re-runs `uv sync` on the next launch when deps change. Free.
- **No capability/ACL changes.** Custom `#[tauri::command]`s are not ACL-gated, and the updater plugin is
  called only from Rust, so no `updater:*` permission is added to `capabilities/default.json`.

## Architecture

### Rust (`tauri/src-tauri/src/lib.rs`)

**Plugin registration** in `run()`, gated for desktop (the crate is desktop-only):

```rust
#[cfg(desktop)]
{
    builder = builder.plugin(tauri_plugin_updater::Builder::new().build());
}
```

(Registration is a small refactor of the current fluent `tauri::Builder::default().plugin(...)...` chain
so the `#[cfg(desktop)]` block can be applied; behavior is otherwise unchanged.)

**Command: `check_for_update`** — returns a serializable summary or `None`.

```rust
#[derive(Serialize)]
struct UpdateInfo {
    version: String,          // the available version
    current_version: String,  // the running version
    notes: Option<String>,    // release notes / body
}

#[tauri::command]
async fn check_for_update(app: tauri::AppHandle) -> Result<Option<UpdateInfo>, String> {
    // app.updater()?.check().await -> Option<Update>; map to UpdateInfo
}
```

**Command: `install_update`** — re-checks (cheap; avoids holding the non-`'static` `Update` across two
IPC calls), downloads with progress, installs, and restarts.

```rust
#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    // let Some(update) = app.updater()?.check().await? else { return Ok(()); };
    // update.download_and_install(on_chunk, on_finish).await?;
    //   - on_chunk emits an "update-progress" event ({ downloaded, total })
    //   - on_finish emits an "update-progress" event at 100%
    // app.restart();  // diverges; never returns
}
```

Both are added to the existing `tauri::generate_handler![...]` list alongside `get_status`, `launch`, etc.

> **Plugin API surface used** (from the plugin's Rust API — exact closure arg types and whether
> `updater()` returns `Result` are pinned during implementation against the installed crate version, not
> guessed here): `UpdaterExt` on `AppHandle` → `updater()` → `check() -> Option<Update>`;
> `Update { version, current_version, body }`; `Update::download_and_install(on_chunk, on_finish)`;
> `AppHandle::restart()`. No `tauri-plugin-process` needed — `restart()` is core.

**Menu** — add a `MenuItem` "Check for Updates…" (id `check-updates`) to the existing app submenu in
`setup()`; add an `on_menu_event` branch that opens the updates window (mirrors `open_logs_window`).

**Events** — reuse the existing event pattern; add one event name: `update-progress` with payload
`{ downloaded: usize, total: Option<u64> }`.

### UI (`tauri/ui/`)

- **`update.js` (new)** — exports (as a global, no bundler) `mountUpdateFlow({ container, mode, onDone })`:
  - Builds the update-card DOM inside `container`.
  - Calls `invoke("check_for_update")`.
  - If an update exists: renders version + notes + `[Install & Restart]` / `[Not now]`. Install →
    `invoke("install_update")`, subscribes to `update-progress`, renders a progress bar; the app restarts
    itself on completion. Not now → `onDone()`.
  - If current: `mode === "launch"` calls `onDone()` immediately (no card shown); `mode === "manual"`
    shows "You're on the latest version."
  - On check/download error: shows the error with a dismiss that calls `onDone()`.
- **`index.html` / `index.js`** — include `update.js`; at the very top of `init()`, before `get_status`,
  run `mountUpdateFlow({ container: main, mode: "launch", onDone: proceedWithNormalInit })`, wrapped in a
  ~5s timeout race so a slow/offline check never blocks startup.
- **`updates.html` / `updates.js` (new, tiny)** — the manual-check window: include `update.js`, call
  `mountUpdateFlow({ container, mode: "manual", onDone: closeWindow })`.

### Data flow

**Launch:** app start → `check_for_update` (≤5s, fail-open) → update? show card : normal init →
Install → `install_update` (download → progress events → install) → `app.restart()` → relaunch on new
version (re-provisions automatically if lockfiles changed).

**Manual:** menu "Check for Updates…" → open `updates` window → `check_for_update` → current: "up to
date" / update: same install path as above. Runs after the main window has navigated to the frontend,
which is why it lives in its own window rather than the main one.

## Configuration (`tauri/src-tauri/tauri.conf.json`)

```jsonc
{
  "bundle": {
    "createUpdaterArtifacts": true
  },
  "plugins": {
    "updater": {
      "pubkey": "<minisign public key, committed>",
      "endpoints": [
        "https://github.com/2389-research/Noospheric-Orrery/releases/latest/download/latest.json"
      ]
    }
  }
}
```

- **Endpoint** is a static GitHub Releases asset URL. `releases/latest/...` resolves to the newest
  **published, non-prerelease** release. The release workflow already publishes on tags and sets
  `prerelease: true` for `-`-suffixed tags — so `v0.5.2` notifies everyone and `v0.5.2-beta.1` does not.
- **Version comparison** relies on the existing "Set app version from tag" step, which stamps
  `tauri.conf.json.version` from the tag at build time. A `v0.5.2` build reports `0.5.2`; `latest.json`
  says `0.5.2`; an installed `0.5.1` sees the newer version. Load-bearing existing behavior — do not
  remove that step.

## Release workflow changes (`.github/workflows/release-desktop.yml`)

Minimal, inside the existing `tauri-apps/tauri-action@v0` step:

- Flip `includeUpdaterJson: false` → `true`. tauri-action then generates `latest.json` (with the per-
  platform `.app.tar.gz` URL + embedded signature) and uploads it to the release.
- Add signing env to that step:
  ```yaml
  env:
    TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
    TAURI_SIGNING_PRIVATE_KEY_PASSWORD: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}
  ```

Everything else stays: the `allow-jit` entitlements gate still runs before publish (a broken build drafts
but never publishes, so no bad `.app.tar.gz` reaches `latest`), the DMG is still notarized/stapled and
`--clobber`-uploaded, and "Publish release" undrafts last — which is what makes `latest.json` reachable.

The `.app.tar.gz` updater bundle is produced by tauri-action from the **notarized** `.app`, so the app a
user lands on after an update is itself notarized and passes Gatekeeper.

## Signing keys & secrets — one-time setup (human-gated)

The updater needs a **minisign** keypair, separate from the Apple Developer ID cert.

1. Generate locally: `npm run tauri signer generate -- -w ~/.tauri/noospheric-updater.key` (produces a
   password-protected private key + a public key).
2. Commit the **public key** into `tauri.conf.json` (`plugins.updater.pubkey`).
3. **Harper adds two GitHub Actions secrets** (I can't and won't touch repo secrets):
   `TAURI_SIGNING_PRIVATE_KEY` (private key content) and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.

**Security note:** whoever holds that private key can publish an update every installed app will trust.
Guard it like the Apple cert; store the private key offline, never in the repo.

## Failure handling & edge cases

- **Offline / slow / GitHub down** at launch → the timeout race fires, the app launches normally
  (fail-open). An update check must never keep the user out of their app.
- **Download or install error** → surfaced in the card with a dismiss; the user proceeds on the current
  version.
- **Signature mismatch** → enforced by the plugin against the pinned `pubkey`; a tampered artifact is
  rejected before install.
- **Race (release published between check and confirm)** → `install_update` re-checks; `None` is a no-op.
- **Intel Mac / unbuilt arch** → no matching platform entry in `latest.json`; no update is offered. Same
  reach as today's single-arch DMG.

## Testing

- **Rust unit tests (TDD)** around the command layer: `Update` → `UpdateInfo` mapping, the "no update"
  (`None`) branch, and error mapping. The network `check()`, `download_and_install`, and `restart` are not
  meaningfully unit-testable and are covered end-to-end.
- **End-to-end (real signed release):** cut a test release one patch above a locally-installed build and
  confirm the launch prompt appears, the download progresses, the app restarts on the new version, and
  the manual "Check for Updates…" path shows both "update available" and "up to date". Minisign
  verification and `app.restart()` can only be trusted against a real signed artifact.
- **No mocks in the e2e path** — real GitHub release, real minisign signature, real bundle swap.

## Open questions / risks

- **Exact plugin Rust signatures** (progress-closure arg types; `updater()` return type; `body` field
  name) are confirmed against the installed crate version during implementation, not assumed here.
- **First real update is only verifiable by shipping one** — the very first build carrying the updater
  can't update *to* itself; verification requires a subsequent signed release. Plan the first two releases
  accordingly (ship the updater in vN, verify the prompt when vN+1 lands).
