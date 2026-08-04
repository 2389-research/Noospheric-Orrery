#!/usr/bin/env bash
# ABOUTME: Exercises nested macOS signing and release workflow ordering.
# ABOUTME: Runs static checks everywhere; skips codesign fixtures outside macOS.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIGN_SCRIPT="$SCRIPT_DIR/sign-macos-resources.sh"
WORKFLOW_FILE="$SCRIPT_DIR/../../.github/workflows/release-desktop.yml"

FAILURE_COUNT=0

record_failure() {
  echo "FAIL: $*" >&2
  ((FAILURE_COUNT += 1))
}

workflow_step_block() {
  local step_name="$1"

  awk -v step_name="$step_name" '
    index($0, "- name: " step_name) { in_step = 1; print; next }
    in_step && /^[[:space:]]+- (name:|uses:)/ { exit }
    in_step { print }
  ' "$WORKFLOW_FILE"
}

import_line="$(grep -n -m1 -- '- name: Import Developer ID certificate' "$WORKFLOW_FILE" | cut -d: -f1 || true)"
sign_line="$(grep -n -m1 -- '- name: Sign staged native resources' "$WORKFLOW_FILE" | cut -d: -f1 || true)"
tauri_action_line="$(grep -n -m1 -- 'uses: tauri-apps/tauri-action@v0' "$WORKFLOW_FILE" | cut -d: -f1 || true)"

[[ -n "$import_line" ]] || record_failure "release workflow is missing the certificate import step"
[[ -n "$sign_line" ]] || record_failure "release workflow is missing the native resource signing step"
[[ -n "$tauri_action_line" ]] || record_failure "release workflow is missing the Tauri action step"
if [[ -n "$import_line" && -n "$sign_line" && -n "$tauri_action_line" ]] \
  && ! ((import_line < sign_line && sign_line < tauri_action_line)); then
  record_failure "release workflow must import the certificate, sign native resources, then run the Tauri action"
fi
if ! workflow_step_block "Import Developer ID certificate" \
  | grep -Eq 'APPLE_KEYCHAIN_PATH=.*GITHUB_ENV'; then
  record_failure "certificate import does not export APPLE_KEYCHAIN_PATH via GITHUB_ENV"
fi
if ! workflow_step_block "Import Developer ID certificate" \
  | grep -Eq '^[[:space:]]+umask[[:space:]]+077'; then
  record_failure "certificate import does not restrict credential file permissions"
fi
if ! workflow_step_block "Sign staged native resources" \
  | grep -Fq 'bash tauri/scripts/sign-macos-resources.sh tauri/src-tauri/resources'; then
  record_failure "native resource signing step does not invoke the signing script"
fi
if ! workflow_step_block "Sign staged native resources" \
  | grep -Eq '^[[:space:]]+APPLE_SIGNING_IDENTITY:[[:space:]]+'; then
  record_failure "native resource signing step does not receive APPLE_SIGNING_IDENTITY"
fi

if ((FAILURE_COUNT > 0)); then
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "SKIP: macOS resource signing test requires macOS"
  exit 0
fi

# shellcheck source=tauri/scripts/sign-macos-resources.sh
source "$SIGN_SCRIPT"

assert_macho() {
  local candidate="$1"

  if ! is_macho "$candidate"; then
    record_failure "expected Mach-O code: $candidate"
  fi
}

assert_runtime_signature() {
  local candidate="$1"
  local signature_details

  if ! codesign --verify --strict "$candidate"; then
    record_failure "invalid signature: $candidate"
    return
  fi
  if ! signature_details="$(codesign --display --verbose=4 "$candidate" 2>&1)"; then
    record_failure "could not inspect signature: $candidate"
    return
  fi
  if ! grep -Eq '^CodeDirectory .*flags=.*runtime' <<<"$signature_details"; then
    record_failure "missing hardened-runtime flag: $candidate"
  fi
}

assert_command_fails() {
  local description="$1"
  local output
  shift

  if output="$("$@" 2>&1)"; then
    record_failure "$description: command succeeded: $output"
  elif [[ -z "$output" ]]; then
    record_failure "$description: command failed without a diagnostic"
  fi
}

FIXTURE_ROOT="$(mktemp -d)"
RESOURCE_DIR="$FIXTURE_ROOT/resources"
EXECUTABLE_FIXTURE="$RESOURCE_DIR/bin/tool"
NODE_FIXTURE="$RESOURCE_DIR/node_modules/addon.node"
DYLIB_FIXTURE="$RESOURCE_DIR/lib/libfixture.dylib"
SO_FIXTURE="$RESOURCE_DIR/lib/libfixture.so"
TEXT_FIXTURE="$RESOURCE_DIR/bin/plain-text-tool"
EMPTY_RESOURCE_DIR="$FIXTURE_ROOT/empty-resources"
TRAVERSAL_RESOURCE_DIR="$FIXTURE_ROOT/traversal-resources"
UNREADABLE_DIRECTORY="$TRAVERSAL_RESOURCE_DIR/unreadable"
DASH_RESOURCE_DIR="$FIXTURE_ROOT/-resources"
DASH_FIXTURE="$DASH_RESOURCE_DIR/dash-tool"

cleanup() {
  chmod 0700 "$UNREADABLE_DIRECTORY" 2>/dev/null || true
  rm -rf "$FIXTURE_ROOT"
}
trap cleanup EXIT

run_dash_prefixed_resource() (
  cd "$FIXTURE_ROOT"
  APPLE_SIGNING_IDENTITY=- bash "$SIGN_SCRIPT" -resources
)

mkdir -p \
  "$(dirname "$EXECUTABLE_FIXTURE")" \
  "$(dirname "$NODE_FIXTURE")" \
  "$(dirname "$DYLIB_FIXTURE")" \
  "$EMPTY_RESOURCE_DIR" \
  "$TRAVERSAL_RESOURCE_DIR" \
  "$DASH_RESOURCE_DIR"
cp /usr/bin/true "$EXECUTABLE_FIXTURE"
cp /usr/bin/true "$NODE_FIXTURE"
cp /usr/bin/true "$DYLIB_FIXTURE"
cp /usr/bin/true "$SO_FIXTURE"
chmod 0755 "$EXECUTABLE_FIXTURE"
chmod 0644 "$NODE_FIXTURE" "$DYLIB_FIXTURE" "$SO_FIXTURE"
printf '#!/usr/bin/env bash\necho "plain text fixture"\n' >"$TEXT_FIXTURE"
chmod 0755 "$TEXT_FIXTURE"
cp /usr/bin/true "$TRAVERSAL_RESOURCE_DIR/tool"
chmod 0755 "$TRAVERSAL_RESOURCE_DIR/tool"
mkdir "$UNREADABLE_DIRECTORY"
cp /usr/bin/true "$UNREADABLE_DIRECTORY/hidden-tool"
chmod 000 "$UNREADABLE_DIRECTORY"
cp /usr/bin/true "$DASH_FIXTURE"
chmod 0755 "$DASH_FIXTURE"

assert_macho "$EXECUTABLE_FIXTURE"
assert_macho "$NODE_FIXTURE"
assert_macho "$DYLIB_FIXTURE"
assert_macho "$SO_FIXTURE"
if is_macho "$TEXT_FIXTURE"; then
  record_failure "plain-text executable detected as Mach-O: $TEXT_FIXTURE"
fi

if ! APPLE_SIGNING_IDENTITY=- bash "$SIGN_SCRIPT" "$RESOURCE_DIR"; then
  record_failure "signing valid resource fixtures failed"
fi

assert_runtime_signature "$EXECUTABLE_FIXTURE"
assert_runtime_signature "$NODE_FIXTURE"
assert_runtime_signature "$DYLIB_FIXTURE"
assert_runtime_signature "$SO_FIXTURE"
if codesign --verify --strict "$TEXT_FIXTURE" >/dev/null 2>&1; then
  record_failure "plain-text executable was signed: $TEXT_FIXTURE"
fi

assert_command_fails \
  "empty resource tree did not fail" \
  env APPLE_SIGNING_IDENTITY=- bash "$SIGN_SCRIPT" "$EMPTY_RESOURCE_DIR"
assert_command_fails \
  "missing APPLE_SIGNING_IDENTITY did not fail" \
  env -u APPLE_SIGNING_IDENTITY bash "$SIGN_SCRIPT" "$RESOURCE_DIR"
assert_command_fails \
  "missing resource directory did not fail" \
  env APPLE_SIGNING_IDENTITY=- bash "$SIGN_SCRIPT" "$FIXTURE_ROOT/missing"
assert_command_fails \
  "resource traversal failure did not fail closed" \
  env APPLE_SIGNING_IDENTITY=- bash "$SIGN_SCRIPT" "$TRAVERSAL_RESOURCE_DIR"

if ! run_dash_prefixed_resource; then
  record_failure "dash-prefixed valid resource directory failed"
else
  assert_runtime_signature "$DASH_FIXTURE"
fi

if ((FAILURE_COUNT > 0)); then
  exit 1
fi
echo "PASS: signed nested Mach-O resources with hardened runtime"
