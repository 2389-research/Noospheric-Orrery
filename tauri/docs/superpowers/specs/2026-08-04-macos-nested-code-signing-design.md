# macOS Nested Code Signing — Design

**Date:** 2026-08-04
**Status:** Approved
**Owner:** Harper + Codex

## Problem

The first `Release Desktop App` dry run reached Apple notarization, but Apple
rejected three native files staged under the app's generic resource tree:

- `resources/bin/uv`
- `resources/frontend/node_modules/@img/sharp-darwin-arm64/lib/sharp-darwin-arm64.node`
- `resources/frontend/node_modules/@img/sharp-libvips-darwin-arm64/lib/libvips-cpp.8.17.3.dylib`

Those upstream files have ad-hoc linker signatures. Tauri signs known app
executables, frameworks, and sidecars before it signs the outer app, but it
does not discover executable code inside `bundle.resources`. Apple therefore
reported an invalid Developer ID signature, no secure timestamp, and, for
`uv`, no hardened runtime. The bundled Node executable passed because the
Node.js Foundation already ships it with all three properties.

## Decision

Import the existing Developer ID certificate into an ephemeral CI keychain
before the Tauri build. After `stage.sh` populates `src-tauri/resources`, run a
repository script that finds Mach-O code among executable files and native
module extensions (`.node`, `.dylib`, and `.so`). Sign each match with the
configured identity, secure timestamp, and hardened runtime, then verify the
signature. Verification requires the configured Developer ID authority, a
secure timestamp, and the hardened-runtime flag. Tauri can then copy the signed
resources and seal the outer app.

The script scans by file type rather than naming today's three failures. This
keeps the signing contract intact when a future frontend or runtime update
adds another native dependency. It does not use `codesign --deep`; Apple
recommends signing each nested code item before its container.

## Components

- `tauri/scripts/sign-macos-resources.sh`: find, sign, and verify staged Mach-O
  files. It requires `APPLE_SIGNING_IDENTITY`, requires
  `APPLE_SIGNING_AUTHORITY` for Developer ID signing, and accepts an optional
  `APPLE_KEYCHAIN_PATH`.
- `tauri/scripts/test-sign-macos-resources.sh`: exercise discovery and signing
  with real Mach-O files and an ad-hoc test identity on macOS. No mocks.
- `.github/workflows/release-desktop.yml`: import the certificate into an
  ephemeral keychain, run the test, sign staged resources, then invoke
  `tauri-action` as before. Delete the decoded certificate and temporary
  keychain as soon as nested signing finishes.

## Failure handling

The signing script fails when the resource directory is missing, no Mach-O
code is found, `codesign` fails, strict verification fails, or a signature has
the wrong authority, no secure timestamp, or no hardened runtime. This stops
the workflow before the slower Rust build and notarization submission.

## Follow-up security work

`stage.sh` pins uv and Node versions, but simmer-sdk follows an unchecked local
or remote HEAD, and the staged inputs lack provenance verification. Resource
provenance validation predates this signing change and needs a separate
security design covering manifests, update policy, and source availability.
This change enforces signing properties on detected Mach-O code and fails when
signing or verification fails; it does not establish provenance.

## Verification

1. Run the shell test before implementation and observe the missing-script
   failure.
2. Run the test after implementation and verify real Mach-O files receive a
   valid hardened-runtime signature while plain executable data is ignored.
3. Run `shellcheck` and `actionlint`.
4. Push the branch and dispatch `Release Desktop App` against it. Apple
   notarization must accept the archive and the artifact step must upload the
   DMG.
5. Download the DMG and run Gatekeeper and stapler checks locally.
