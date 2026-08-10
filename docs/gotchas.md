# Gotchas

Running log of non-obvious traps in this codebase — things that cost a
debugging session once and shouldn't cost another. Add an entry when a
correction or surprise teaches a pattern that isn't visible from the code
itself. Newest first.

## A Tauri window can't invoke commands unless its label is in a capability's `windows` list

*First hit: 2026-08-10, building the manual "Check for Updates…" window.*

Tauri v2 gates IPC per window. A webview window may call `invoke(...)` or `listen(...)` only if its label appears in the `windows` array of a capability that grants the matching permission. The manual updates window is opened programmatically (`open_updates_window` in `tauri/src-tauri/src/lib.rs`) with the label `"updates"`, so that label had to be added to `tauri/src-tauri/capabilities/default.json`:

```json
"windows": ["main", "logs", "updates"]
```

**Tell:** the window renders fine but every `invoke`/`listen` rejects or silently no-ops — the UI just sits there. It's not a JS bug; the window isn't authorized. Add the label to the capability, don't chase the frontend.

## A Rust command returning `Option<T>` crosses IPC as JSON `null`

*First hit: 2026-08-10, wiring the update check.*

`check_for_update` is `Result<Option<UpdateInfo>, String>` (`tauri/src-tauri/src/lib.rs`); `Ok(None)` means "already up to date." Across the IPC boundary `None` becomes JSON `null` (falsy in JS) and `Some(info)` becomes an object, so the frontend branches on truthiness — `update.js` does `if (!info) { /* up to date */ }`. Swap the command to return a sentinel object or an empty struct instead of `None` and that check breaks silently: the app then thinks an update is always available. Keep the up-to-date signal as `Ok(None)` → `null`.

## Release notarization fails with HTTP 403 "required agreement is missing"

*First hit: 2026-08-08, cutting v0.5.1 (the release for the #52 JIT-signing fix).*

The desktop release workflow (`.github/workflows/release-desktop.yml`, triggered by `v*` tags) can fail inside the **Build, sign, notarize** step with:

> failed to notarize app: Error: HTTP status code: 403. A required agreement is missing or has expired.

This is **not** a code, entitlements, or signing-config bug. Someone with the **Account Holder / Admin** role on the Apple Developer team must accept an updated Apple Developer Program License Agreement at <https://developer.apple.com/account> (usually a banner prompting to review/accept). Apple revises the agreement periodically and blocks every notarization submission with this 403 until it's signed.

**Diagnosis tell:** all signing steps pass (cert import, native resource signing, the `Test native resource signing` harness); only the notarization submission fails. The API key authenticated fine — a 403 with an agreement message, not a 401 — so credentials are not the problem.

**Recovery:** after the agreement is signed, re-run the same run with `gh run rerun <run-id>` (retries on the same tag ref). No new tag or commit needed; don't delete/re-push the tag. The `Remove notarization API key` cleanup step runs `if: always()`, so a failed run leaves no secret behind.
