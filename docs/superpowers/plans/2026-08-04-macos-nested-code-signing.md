# macOS Nested Code Signing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Sign every staged Mach-O resource with the project's Developer ID before Tauri seals and notarizes the macOS app.

**Architecture:** A shell script discovers native code in `src-tauri/resources`, signs each file with the configured identity, timestamp, and hardened runtime, and verifies it. The release workflow imports the certificate into an ephemeral keychain before calling that script; Tauri then signs the outer bundle through its existing path.

**Tech Stack:** Bash, macOS `codesign` and `security`, GitHub Actions, Tauri 2, shellcheck, actionlint.

**Spec:** `tauri/docs/superpowers/specs/2026-08-04-macos-nested-code-signing-design.md`

---

### Task 1: Regression test and signing script

**Files:**
- Create: `tauri/scripts/test-sign-macos-resources.sh`
- Create: `tauri/scripts/sign-macos-resources.sh`

**Step 1: Write the failing test**

Create a shell test that:

- exits cleanly with a skip message outside macOS;
- copies `/usr/bin/true` into a temporary resource tree as an executable,
  `.node`, and `.dylib` fixture;
- adds an executable plain-text file;
- sources `sign-macos-resources.sh` and checks Mach-O detection;
- invokes the script with `APPLE_SIGNING_IDENTITY=-`;
- verifies the three Mach-O fixtures with `codesign --verify --strict` and
  confirms hardened-runtime flags;
- confirms the plain-text executable was not signed.

**Step 2: Run the test to verify it fails**

Run: `bash tauri/scripts/test-sign-macos-resources.sh`

Expected: FAIL because `tauri/scripts/sign-macos-resources.sh` does not exist.

**Step 3: Write the minimal signing script**

The script must:

- require a resource directory argument and `APPLE_SIGNING_IDENTITY`;
- reject non-macOS hosts;
- inspect executable files plus `*.node`, `*.dylib`, and `*.so` files;
- use `file` to keep only Mach-O code;
- run `codesign --force --sign IDENTITY --timestamp --options runtime` for
  each match (`codesign(1)` requires `--sign` before `--options`; the reverse
  order silently ignores the hardened-runtime option);
- pass `--keychain "$APPLE_KEYCHAIN_PATH"` when that variable is set;
- run `codesign --verify --strict --verbose=2` for each signed file;
- fail if no Mach-O code was found.

**Step 4: Run the test to verify it passes**

Run: `bash tauri/scripts/test-sign-macos-resources.sh`

Expected: PASS with three signed fixtures and no signature on the text file.

**Step 5: Lint the scripts**

Run: `shellcheck tauri/scripts/sign-macos-resources.sh tauri/scripts/test-sign-macos-resources.sh`

Expected: no output.

**Step 6: Commit**

```bash
git add tauri/scripts/sign-macos-resources.sh tauri/scripts/test-sign-macos-resources.sh
git commit -m "fix(tauri): sign nested macOS resource binaries"
```

---

### Task 2: Release workflow integration

**Files:**
- Modify: `.github/workflows/release-desktop.yml`

**Step 1: Add the failing static assertion**

Extend the shell test to assert that the release workflow runs, in order:

1. certificate import;
2. nested resource signing;
3. `tauri-apps/tauri-action`.

It must also assert that the signing step passes both
`APPLE_SIGNING_IDENTITY` and `APPLE_KEYCHAIN_PATH`.

**Step 2: Run the test to verify it fails**

Run: `bash tauri/scripts/test-sign-macos-resources.sh`

Expected: FAIL because the workflow has no certificate-import or nested-signing steps.

**Step 3: Import and use the certificate**

After generating `KEYCHAIN_PASSWORD`, add workflow steps that:

- decode `APPLE_CERTIFICATE` into `$RUNNER_TEMP/certificate.p12`;
- create and unlock `$RUNNER_TEMP/build.keychain-db`;
- import the certificate with access for `/usr/bin/codesign`;
- set the key partition list;
- export `APPLE_KEYCHAIN_PATH` through `GITHUB_ENV`;
- run the real shell test;
- run `sign-macos-resources.sh tauri/src-tauri/resources` with the signing
  identity secret;
- delete the decoded certificate and temporary keychain in an `always()` step
  immediately after nested signing.

Keep the existing Tauri action environment so Tauri can manage its own
outer-bundle signing keychain.

**Step 4: Run tests and linters**

Run:

```bash
bash tauri/scripts/test-sign-macos-resources.sh
shellcheck tauri/scripts/sign-macos-resources.sh tauri/scripts/test-sign-macos-resources.sh
actionlint .github/workflows/release-desktop.yml
```

Expected: all commands exit zero with no warnings.

**Step 5: Commit**

```bash
git add .github/workflows/release-desktop.yml tauri/scripts/test-sign-macos-resources.sh
git commit -m "fix(ci): sign native resources before notarization"
```

---

### Task 3: Real release-pipeline verification

**Files:** none.

**Step 1: Run local checks**

Run the repository's available test suites plus the shell test, shellcheck,
actionlint, and a local signed-resource scenario using the installed Developer
ID identity.

Expected: all relevant checks exit zero without new warnings.

**Step 2: Review**

Review the complete diff for spec compliance, security, shell correctness,
secret handling, and unrelated changes.

**Step 3: Push and dispatch**

Push `fix/macos-nested-code-signing`, then run:

```bash
gh workflow run release-desktop.yml --ref fix/macos-nested-code-signing
```

Watch the new run with `gh run watch --exit-status` and inspect its complete
failure log if it fails.

Expected: Apple accepts notarization and the dry-run DMG artifact uploads.

**Step 4: Verify the artifact**

Download the DMG into a temporary directory. Mount it read-only, run
`spctl -a -vv` on `Noospheric.app`, run `xcrun stapler validate` on the DMG,
then detach it.

Expected: Gatekeeper reports `accepted` and `source=Notarized Developer ID`;
stapler validates the ticket.

**Step 5: Record and commit the result**

Update this plan's execution status with the run ID and Gatekeeper result,
then commit the update.
