# Desktop Release Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pushing a `v*` tag builds the Tauri desktop app on macOS CI, signs it with the 2389 Developer ID cert, notarizes it with Apple, and auto-publishes a GitHub Release with the `.dmg`.

**Architecture:** One new self-contained workflow (`release-desktop.yml`) on a `macos-latest` (arm64) runner: `stage.sh` → version-from-tag patch → `tauri-apps/tauri-action` (build/sign/notarize, draft release) → flip draft live. Six repo secrets sourced from Harper's local iCloud cert stash. `release-images.yml` is untouched.

**Tech Stack:** GitHub Actions, tauri-apps/tauri-action@v0, Tauri 2 CLI, jq, gh CLI, actionlint.

**Spec:** `tauri/docs/superpowers/specs/2026-08-04-desktop-release-workflow-design.md`

## Global Constraints

- Platform: `macos-latest` (Apple silicon) only. No universal builds — `stage.sh` fetches arch-specific `uv`/`node`.
- Signing identity literal: `Developer ID Application: 2389 Research, Inc (HD9NM9NSMK)`
- Notarization: App Store Connect API key `BHN2KMQ235` (file path via `APPLE_API_KEY_PATH`, not content).
- `release-images.yml` must not be modified.
- Secret values must never be echoed into terminal output or the conversation — pipe files directly into `gh secret set`.
- Credential source dir (this machine only): `/Users/harper/workspace/icloud-2389/Apple/2389/`
- Tag runs create a **draft** release first; publish (`--draft=false`) only as the final step.
- `workflow_dispatch` runs must not create or modify any release.
- Repo: `2389-research/Noospheric-Orrery`, work branch `feat/desktop-release-workflow`.

**Testing note:** A GitHub workflow has no unit-test harness. The test cycle per the spec is: `actionlint` (static) at task time, then a real `workflow_dispatch` dry run (build+sign+notarize on a live runner) after merge, verified with Gatekeeper tooling (`spctl`, `stapler`) on a local Mac. TDD's red/green loop doesn't apply to YAML; every task still ends with a concrete verification step.

---

### Task 1: `release-desktop.yml` workflow

**Files:**
- Create: `.github/workflows/release-desktop.yml`

**Interfaces:**
- Consumes: `tauri/scripts/stage.sh` (existing, self-contained), `tauri/package.json` (`npm ci` installs `@tauri-apps/cli`), repo secrets from Task 2 (`APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_API_ISSUER`, `APPLE_API_KEY`, `APPLE_API_KEY_CONTENT`).
- Produces: on `v*` tag push — a published GitHub Release named `Noospheric v<X.Y.Z>` with the signed+notarized `.dmg`; on `workflow_dispatch` — workflow artifacts only.

- [ ] **Step 1: Verify tauri-action input names against its action.yml** (README prose disagrees with itself about `includeUpdaterJson` vs `uploadUpdaterJson` — check the source of truth):

```bash
curl -s https://raw.githubusercontent.com/tauri-apps/tauri-action/v0/action.yml \
  | grep -E '^  [a-zA-Z]+:' 
```

Expected: a list of input names. Confirm the exact names for: `projectPath`, `tagName`, `releaseName`, `releaseDraft`, `prerelease`, `uploadWorkflowArtifacts` (or nearest equivalent), and the updater-json toggle. If any name below differs from reality, use reality and note it in the commit message.

- [ ] **Step 2: Write `.github/workflows/release-desktop.yml`** (adjust only the input names Step 1 disproved):

```yaml
# ABOUTME: Build, sign, and notarize the Tauri desktop app on macOS, then
# ABOUTME: publish a GitHub Release on v* tags (dry-run via workflow_dispatch).

name: Release Desktop App

on:
  push:
    tags: ["v*"]
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build-macos:
    runs-on: macos-latest
    timeout-minutes: 90
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Install Rust (stable)
        uses: dtolnay/rust-toolchain@stable

      - name: Cache cargo build
        uses: Swatinem/rust-cache@v2
        with:
          workspaces: tauri/src-tauri

      - name: Stage services, frontend, and runtimes
        run: bash tauri/scripts/stage.sh

      - name: Set app version from tag
        if: github.ref_type == 'tag'
        run: |
          v="${GITHUB_REF_NAME#v}"
          jq --arg v "$v" '.version = $v' tauri/src-tauri/tauri.conf.json > "$RUNNER_TEMP/tauri.conf.json"
          mv "$RUNNER_TEMP/tauri.conf.json" tauri/src-tauri/tauri.conf.json
          echo "Building version $v"

      - name: Install Tauri CLI
        run: npm ci
        working-directory: tauri

      - name: Write App Store Connect API key
        run: |
          printf '%s\n' "$APPLE_API_KEY_CONTENT" > "$RUNNER_TEMP/AuthKey.p8"
          echo "APPLE_API_KEY_PATH=$RUNNER_TEMP/AuthKey.p8" >> "$GITHUB_ENV"
        env:
          APPLE_API_KEY_CONTENT: ${{ secrets.APPLE_API_KEY_CONTENT }}

      - name: Generate ephemeral keychain password
        run: |
          pw="$(openssl rand -hex 24)"
          echo "::add-mask::$pw"
          echo "KEYCHAIN_PASSWORD=$pw" >> "$GITHUB_ENV"

      - name: Build, sign, notarize (and draft release on tags)
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
          APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}
          APPLE_SIGNING_IDENTITY: ${{ secrets.APPLE_SIGNING_IDENTITY }}
          APPLE_API_ISSUER: ${{ secrets.APPLE_API_ISSUER }}
          APPLE_API_KEY: ${{ secrets.APPLE_API_KEY }}
          # APPLE_API_KEY_PATH and KEYCHAIN_PASSWORD arrive via GITHUB_ENV above
        with:
          projectPath: tauri
          tagName: ${{ github.ref_type == 'tag' && github.ref_name || '' }}
          releaseName: ${{ github.ref_type == 'tag' && format('Noospheric {0}', github.ref_name) || '' }}
          releaseDraft: true
          prerelease: ${{ github.ref_type == 'tag' && contains(github.ref_name, '-') }}
          includeUpdaterJson: false
          uploadWorkflowArtifacts: ${{ github.ref_type != 'tag' }}

      - name: Publish release
        if: github.ref_type == 'tag'
        run: gh release edit "$GITHUB_REF_NAME" --draft=false
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GH_REPO: ${{ github.repository }}
```

- [ ] **Step 3: Lint the workflow**

Run: `actionlint .github/workflows/release-desktop.yml`
Expected: no output (clean). Fix anything it reports — shellcheck findings included.

- [ ] **Step 4: Sanity-check the two trigger paths by reading the conditionals**

Verify by inspection (each `if:`/expression, one by one): tag push → version patched, release inputs set, draft flipped at the end; dispatch → no version patch, empty `tagName`/`releaseName` (tauri-action skips release work when `tagName` is empty), artifacts uploaded, publish step skipped. Confirm `permissions: contents: write` is present at workflow level.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release-desktop.yml
git commit -m "feat(ci): build, sign, notarize + release desktop app on v tags"
```

---

### Task 2: Repo secrets

**Files:** none (GitHub repo state). Reads local credential files only.

**Interfaces:**
- Consumes: `/Users/harper/workspace/icloud-2389/Apple/2389/{Certificates.p12,Certificates.p12.password.txt,Issuer-id.txt,AuthKey_BHN2KMQ235.p8}`
- Produces: the six repo secrets Task 1's workflow reads.

- [ ] **Step 1: Set all six secrets, piping values (never echoing them)**

Trailing newlines matter: single-line values go through `tr -d '\n'` (a stray newline in a password breaks cert import); the `.p8` must keep its internal newlines and is piped verbatim; base64 whitespace is harmless to Tauri's decoder.

```bash
cd /Users/harper/workspace/icloud-2389/Apple/2389
REPO=2389-research/Noospheric-Orrery
base64 -i Certificates.p12 | gh secret set APPLE_CERTIFICATE --repo "$REPO"
tr -d '\n' < Certificates.p12.password.txt | gh secret set APPLE_CERTIFICATE_PASSWORD --repo "$REPO"
printf '%s' 'Developer ID Application: 2389 Research, Inc (HD9NM9NSMK)' | gh secret set APPLE_SIGNING_IDENTITY --repo "$REPO"
tr -d '\n' < Issuer-id.txt | gh secret set APPLE_API_ISSUER --repo "$REPO"
printf '%s' 'BHN2KMQ235' | gh secret set APPLE_API_KEY --repo "$REPO"
gh secret set APPLE_API_KEY_CONTENT --repo "$REPO" < AuthKey_BHN2KMQ235.p8
```

- [ ] **Step 2: Verify all six exist**

Run: `gh secret list --repo 2389-research/Noospheric-Orrery`
Expected: exactly `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_API_ISSUER`, `APPLE_API_KEY`, `APPLE_API_KEY_CONTENT` with today's timestamps. Nothing to commit.

---

### Task 3: Docs

**Files:**
- Modify: `tauri/README.md` (the "Not yet done (v1 scope)" list; add a release section)

**Interfaces:**
- Consumes: the workflow behavior defined in Task 1 (tag-driven version, dry-run dispatch).
- Produces: user-facing release instructions.

- [ ] **Step 1: Update `tauri/README.md`**

In the "Not yet done (v1 scope)" list, replace the line:

```markdown
- macOS / Windows staging targets (stage.sh has the platform table; needs per-platform runs + signing)
```

with:

```markdown
- Windows and Intel-macOS staging targets (stage.sh has the platform table; needs per-platform runs + signing)
```

After the "## Building" section, add:

```markdown
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
```

- [ ] **Step 2: Verify rendering**

Run: `grep -n "Releasing" tauri/README.md`
Expected: the new section present once, between "Building" and "Repo layout".

- [ ] **Step 3: Commit**

```bash
git add tauri/README.md
git commit -m "docs(tauri): document v-tag release flow and dry-run dispatch"
```

---

### Task 4: Merge, dry-run, verify the artifact

**Files:** none new. This task exercises the pipeline for real.

**Interfaces:**
- Consumes: merged workflow on `main` (GitHub only registers `workflow_dispatch` workflows from the default branch), secrets from Task 2.
- Produces: a green dry run and a locally verified signed+notarized `.dmg`.

- [ ] **Step 1: Push branch, open PR, wait for checks**

```bash
git push -u origin feat/desktop-release-workflow
gh pr create --title "feat(ci): signed desktop releases on v tags" \
  --body "Per tauri/docs/superpowers/specs/2026-08-04-desktop-release-workflow-design.md. New standalone workflow; release-images.yml untouched. Dry-run dispatch exists for testing without a tag."
gh pr checks --watch
```

Expected: existing test suite green (this PR touches no code the tests cover).

- [ ] **Step 2: Merge (checkpoint — Harper approves the PR merge)**

```bash
gh pr merge --squash
```

- [ ] **Step 3: Dispatch the dry run and watch it**

```bash
gh workflow run release-desktop.yml --ref main
sleep 10
gh run list --workflow=release-desktop.yml --limit 1
gh run watch "$(gh run list --workflow=release-desktop.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
```

Expected: run succeeds. Likeliest first failures (per spec): `stage.sh` on a macOS runner, cert import, notarization auth. Debug from the run logs (`gh run view --log-failed`), fix on a branch, repeat this task.

- [ ] **Step 4: Download the artifact and verify Gatekeeper accepts it**

```bash
cd "$(mktemp -d)"
gh run download "$(gh run list --workflow=release-desktop.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --repo 2389-research/Noospheric-Orrery
find . -name '*.dmg'
hdiutil attach -nobrowse -readonly ./**/*.dmg
spctl -a -vv /Volumes/Noospheric*/Noospheric.app
xcrun stapler validate ./**/*.dmg
hdiutil detach /Volumes/Noospheric*
```

Expected: `spctl` says `accepted` with `source=Notarized Developer ID`; `stapler validate` says the ticket is worked. If `spctl` says rejected or `source=Unnotarized`, the pipeline is NOT done — debug notarization before claiming success.

- [ ] **Step 5: Report** — dry run green + local Gatekeeper verdict pasted into the conversation. Actual `v*` tagging is Harper's move (use the releasing-software skill when he asks).

---

## Self-review notes

- Spec coverage: workflow (Task 1), secrets (Task 2), README (Task 3), dry-run + Gatekeeper verification (Task 4). Spec's "known consequence" needs no task (it's the absence of a change). Version-from-tag, draft-then-flip, prerelease detection, updater-json off, KEYCHAIN_PASSWORD generation — all in Task 1's YAML.
- The `includeUpdaterJson`/`uploadWorkflowArtifacts` names carry a verification step (Task 1 Step 1) because sources disagree; the YAML is written with the best-evidence names and Step 1 corrects them against action.yml before commit.
- Type consistency: secret names identical across Task 1 env block and Task 2 commands (six names, matched).
