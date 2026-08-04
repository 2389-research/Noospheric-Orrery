# Desktop Release Workflow — Design

**Date:** 2026-08-04
**Status:** Approved (pending spec review)
**Owner:** Harper + Claude

## Goal

Pushing a `v*` tag builds the Tauri desktop app on CI, signs it with the 2389
Developer ID certificate, notarizes it with Apple, and publishes a GitHub
Release with the `.dmg` attached. No manual steps after the tag push.

## Decisions (settled during brainstorming)

| Decision | Choice |
|---|---|
| Platforms | macOS Apple silicon (`aarch64`) only |
| Builder | `tauri-apps/tauri-action` (official action) |
| Signing identity | `Developer ID Application: 2389 Research, Inc (HD9NM9NSMK)` — expires Aug 2030 |
| Notarization | App Store Connect API key `BHN2KMQ235` (the "developer API" key) |
| Publish mode | Auto-publish, via draft-then-flip (see below) |
| App version | Derived from the tag (`v0.5.0` → `0.5.0`), patched into `tauri.conf.json` before build |
| Existing workflows | **`release-images.yml` is not modified** (Harper's call) |

Universal binaries are off the table: `stage.sh` downloads `uv`/`node` for the
*current* platform, so each arch needs its own runner. One arch, one runner.

## New workflow: `.github/workflows/release-desktop.yml`

Triggers:

- `push: tags: ['v*']` — full run: build → sign → notarize → release.
- `workflow_dispatch` — dry run: build → sign → notarize, upload the `.dmg` as
  a workflow artifact, **no release**. For testing the signing pipeline without
  burning a version tag.

Job (single, `macos-latest` = arm64, `timeout-minutes: 90` — notarization
latency varies; `permissions: contents: write` for release creation and the
draft flip):

1. Checkout.
2. Rust stable toolchain + `swatinem/rust-cache` (keyed on
   `tauri/src-tauri/Cargo.lock`).
3. `bash tauri/scripts/stage.sh` — stages services, builds the Next.js frontend
   (the script downloads its own pinned node), fetches `uv`/`node` for
   darwin-arm64, clones simmer-sdk.
4. Patch version: `jq --arg v "${GITHUB_REF_NAME#v}" '.version = $v'` into
   `tauri/src-tauri/tauri.conf.json` (tag runs only; dispatch runs keep the
   checked-in version).
5. `npm ci` in `tauri/` (tauri CLI).
6. Write the App Store Connect `.p8` from the secret to `$RUNNER_TEMP`, export
   `APPLE_API_KEY_PATH`.
7. `tauri-apps/tauri-action` with `projectPath: tauri`, signing/notarization
   env (below). Tag runs: `tagName` = the pushed tag, `releaseName` =
   `Noospheric v0.5.0` (product name + tag),
   `releaseDraft: true`, `prerelease: ${{ contains(github.ref_name, '-') }}`.
   Dispatch runs: no release inputs, `uploadWorkflowArtifacts` instead.
8. Tag runs only: flip the draft live —
   `gh release edit "$GITHUB_REF_NAME" --draft=false`.

### Why draft-then-flip instead of publishing directly

`tauri-action` creates the release *before* artifacts finish uploading. A
mid-build failure would otherwise leave a broken, already-public release. The
draft becomes visible only after everything succeeded — same zero-click
outcome, atomic result. A failed run leaves a draft (invisible to users) for
debugging; re-running after a fix reuses it.

### Signing / notarization contract (verified against Tauri v2 docs 2026-08-04)

The Tauri CLI reads these env vars during `tauri build`; the action passes them
through:

- `APPLE_CERTIFICATE` — base64 `.p12`
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_SIGNING_IDENTITY`
- `APPLE_API_ISSUER`, `APPLE_API_KEY`, `APPLE_API_KEY_PATH` — notarization via
  App Store Connect API key (path to the `.p8`, not its content)

Implementation must confirm whether the CI keychain import also wants
`KEYCHAIN_PASSWORD`; if so, generate a random one in-workflow (not a repo
secret). Set `includeUpdaterJson: false` — no updater is configured.

## Repo secrets (set via `gh secret set`, values piped from local files)

Source of truth: `/Users/harper/workspace/icloud-2389/Apple/2389/` (Harper's
iCloud, this machine only). Secret values never pass through an agent
conversation — pipe file → `gh secret set` directly.

| Secret | Source file |
|---|---|
| `APPLE_CERTIFICATE` | `base64 < Certificates.p12` (Developer ID Application + private key) |
| `APPLE_CERTIFICATE_PASSWORD` | `Certificates.p12.password.txt` |
| `APPLE_SIGNING_IDENTITY` | literal `Developer ID Application: 2389 Research, Inc (HD9NM9NSMK)` |
| `APPLE_API_ISSUER` | `Issuer-id.txt` |
| `APPLE_API_KEY` | literal `BHN2KMQ235` |
| `APPLE_API_KEY_CONTENT` | `AuthKey_BHN2KMQ235.p8` |

(`apple_dist.p12` / `DistCertificates.p12` are Apple *Distribution* certs —
App Store only, wrong kind for direct `.dmg` distribution. Not used.)

## Known consequence: release-images.yml won't fire on bot releases

`release-images.yml` triggers on `release: published`, but releases published
with a workflow's `GITHUB_TOKEN` do not emit events to other workflows
(GitHub's recursion guard). Since `release-images.yml` stays untouched:

- Docker images keep building on every push to `main` (`:latest`, `:sha`).
- Semver-tagged Docker images (`:0.5.0`) only happen when a human publishes a
  release with their own token.

Accepted. If semver image tags per tag-push are wanted later: either add a
`push: tags` trigger to `release-images.yml` or publish the release with a PAT.

## Verification

1. Before any tag: `workflow_dispatch` dry run must go green (build + sign +
   notarize on a real runner — `stage.sh` has never run on macOS CI; this is
   the likeliest first failure).
2. Download the dry-run `.dmg` on a real Mac: `spctl -a -vv` against the
   mounted `.app` and `xcrun stapler validate` against the `.dmg` — the actual
   Gatekeeper verdict, not just green CI.
3. First real tag: confirm the release publishes, the `.dmg` version matches
   the tag, and the asset installs/launches on a clean machine.

## Out of scope (explicitly)

- Linux / Windows / Intel-macOS builds
- Tauri auto-updater + update manifest
- PR smoke-builds of the Tauri app
- Any change to `release-images.yml`
- Migrating the App Store distribution certs

## Docs to update alongside implementation

- `tauri/README.md` — "Not yet done" list (macOS signing lands), plus a short
  "cutting a release" section (bump nothing, push a `v*` tag).
