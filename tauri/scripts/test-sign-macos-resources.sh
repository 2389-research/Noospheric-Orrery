#!/usr/bin/env bash
# ABOUTME: Exercises nested macOS resource signing with real Mach-O fixtures.
# ABOUTME: Skips cleanly on non-macOS hosts where codesign is unavailable.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "SKIP: macOS resource signing test requires macOS"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIGN_SCRIPT="$SCRIPT_DIR/sign-macos-resources.sh"

# shellcheck source=tauri/scripts/sign-macos-resources.sh
source "$SIGN_SCRIPT"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_macho() {
  local candidate="$1"
  is_macho "$candidate" || fail "expected Mach-O code: $candidate"
}

assert_runtime_signature() {
  local candidate="$1"
  local signature_details

  codesign --verify --strict "$candidate"
  signature_details="$(codesign --display --verbose=4 "$candidate" 2>&1)"
  grep -Eq '^CodeDirectory .*flags=.*runtime' <<<"$signature_details" \
    || fail "missing hardened-runtime flag: $candidate"
}

FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf "$FIXTURE_ROOT"' EXIT
RESOURCE_DIR="$FIXTURE_ROOT/resources"
EXECUTABLE_FIXTURE="$RESOURCE_DIR/bin/tool"
NODE_FIXTURE="$RESOURCE_DIR/node_modules/addon.node"
DYLIB_FIXTURE="$RESOURCE_DIR/lib/libfixture.dylib"
TEXT_FIXTURE="$RESOURCE_DIR/bin/plain-text-tool"

mkdir -p \
  "$(dirname "$EXECUTABLE_FIXTURE")" \
  "$(dirname "$NODE_FIXTURE")" \
  "$(dirname "$DYLIB_FIXTURE")"
cp /usr/bin/true "$EXECUTABLE_FIXTURE"
cp /usr/bin/true "$NODE_FIXTURE"
cp /usr/bin/true "$DYLIB_FIXTURE"
chmod 0755 "$EXECUTABLE_FIXTURE"
chmod 0644 "$NODE_FIXTURE" "$DYLIB_FIXTURE"
printf '#!/usr/bin/env bash\necho "plain text fixture"\n' >"$TEXT_FIXTURE"
chmod 0755 "$TEXT_FIXTURE"

assert_macho "$EXECUTABLE_FIXTURE"
assert_macho "$NODE_FIXTURE"
assert_macho "$DYLIB_FIXTURE"
if is_macho "$TEXT_FIXTURE"; then
  fail "plain-text executable detected as Mach-O: $TEXT_FIXTURE"
fi

APPLE_SIGNING_IDENTITY=- bash "$SIGN_SCRIPT" "$RESOURCE_DIR"

assert_runtime_signature "$EXECUTABLE_FIXTURE"
assert_runtime_signature "$NODE_FIXTURE"
assert_runtime_signature "$DYLIB_FIXTURE"
if codesign --verify --strict "$TEXT_FIXTURE" >/dev/null 2>&1; then
  fail "plain-text executable was signed: $TEXT_FIXTURE"
fi

echo "PASS: signed nested Mach-O resources with hardened runtime"
