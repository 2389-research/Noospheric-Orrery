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
cleanup_line="$(grep -n -m1 -- '- name: Remove nested-signing credentials' "$WORKFLOW_FILE" | cut -d: -f1 || true)"
tauri_action_line="$(grep -n -m1 -- 'uses: tauri-apps/tauri-action@v0' "$WORKFLOW_FILE" | cut -d: -f1 || true)"
verify_node_line="$(grep -n -m1 -- '- name: Verify bundled node entitlements' "$WORKFLOW_FILE" | cut -d: -f1 || true)"
notarize_dmg_line="$(grep -n -m1 -- '- name: Notarize and staple disk image' "$WORKFLOW_FILE" | cut -d: -f1 || true)"
upload_dry_run_line="$(grep -n -m1 -- '- name: Upload dry-run artifacts' "$WORKFLOW_FILE" | cut -d: -f1 || true)"
replace_release_dmg_line="$(grep -n -m1 -- '- name: Replace release disk image' "$WORKFLOW_FILE" | cut -d: -f1 || true)"
publish_release_line="$(grep -n -m1 -- '- name: Publish release' "$WORKFLOW_FILE" | cut -d: -f1 || true)"
api_key_cleanup_line="$(grep -n -m1 -- '- name: Remove notarization API key' "$WORKFLOW_FILE" | cut -d: -f1 || true)"
api_key_block="$(workflow_step_block "Write App Store Connect API key")"
import_block="$(workflow_step_block "Import Developer ID certificate")"
test_block="$(workflow_step_block "Test native resource signing")"
sign_block="$(workflow_step_block "Sign staged native resources")"
cleanup_block="$(workflow_step_block "Remove nested-signing credentials")"
verify_node_block="$(workflow_step_block "Verify bundled node entitlements")"
notarize_dmg_block="$(workflow_step_block "Notarize and staple disk image")"
upload_dry_run_block="$(workflow_step_block "Upload dry-run artifacts")"
replace_release_dmg_block="$(workflow_step_block "Replace release disk image")"
publish_release_block="$(workflow_step_block "Publish release")"
api_key_cleanup_block="$(workflow_step_block "Remove notarization API key")"

[[ -n "$import_line" ]] || record_failure "release workflow is missing the certificate import step"
[[ -n "$sign_line" ]] || record_failure "release workflow is missing the native resource signing step"
[[ -n "$cleanup_line" ]] || record_failure "release workflow is missing the nested-signing cleanup step"
[[ -n "$tauri_action_line" ]] || record_failure "release workflow is missing the Tauri action step"
[[ -n "$verify_node_line" ]] || record_failure "release workflow does not verify the bundled node entitlements"
[[ -n "$notarize_dmg_line" ]] || record_failure "release workflow is missing disk-image notarization"
[[ -n "$upload_dry_run_line" ]] || record_failure "release workflow is missing dry-run artifact upload"
[[ -n "$replace_release_dmg_line" ]] || record_failure "release workflow does not replace the draft release's pre-notarization disk image"
[[ -n "$publish_release_line" ]] || record_failure "release workflow is missing release publication"
[[ -n "$api_key_cleanup_line" ]] || record_failure "release workflow does not remove the notarization API key"
if [[ -n "$import_line" && -n "$sign_line" && -n "$cleanup_line" && -n "$tauri_action_line" ]] \
  && ! ((import_line < sign_line && sign_line < cleanup_line && cleanup_line < tauri_action_line)); then
  record_failure "release workflow must import the certificate, sign native resources, clean credentials, then run the Tauri action"
fi
if [[ -n "$tauri_action_line" && -n "$notarize_dmg_line" && -n "$api_key_cleanup_line" && -n "$upload_dry_run_line" \
  && -n "$replace_release_dmg_line" && -n "$publish_release_line" ]] \
  && ! ((tauri_action_line < notarize_dmg_line \
    && notarize_dmg_line < api_key_cleanup_line \
    && api_key_cleanup_line < upload_dry_run_line \
    && upload_dry_run_line < replace_release_dmg_line \
    && replace_release_dmg_line < publish_release_line)); then
  record_failure "release workflow must notarize the DMG before uploading or publishing it"
fi
# Guards the v0.5.0 regression at the finish line: if the app bundling step
# ever re-signs nested resources, node must still carry allow-jit before the
# disk image is notarized, stapled, or published (issue #52).
if [[ -n "$tauri_action_line" && -n "$verify_node_line" && -n "$notarize_dmg_line" ]] \
  && ! ((tauri_action_line < verify_node_line && verify_node_line < notarize_dmg_line)); then
  record_failure "bundled node entitlement verification must run between the Tauri action and notarization"
fi
for verify_node_command in \
  'bundle/macos' \
  'Contents/Resources/resources/bin/node' \
  'codesign --display --entitlements' \
  'plutil -extract' \
  'com\.apple\.security\.cs\.allow-jit' \
  '-expect bool'; do
  if ! grep -Fq -- "$verify_node_command" <<<"$verify_node_block"; then
    record_failure "bundled node entitlement verification is missing: $verify_node_command"
  fi
done
api_key_umask_line="$(grep -n -m1 -E '^[[:space:]]+umask[[:space:]]+077' <<<"$api_key_block" | cut -d: -f1 || true)"
api_key_write_line="$(grep -n -m1 -F "printf '%s\\n' \"\$APPLE_API_KEY_CONTENT\" > \"\$RUNNER_TEMP/AuthKey.p8\"" <<<"$api_key_block" | cut -d: -f1 || true)"
if [[ -z "$api_key_umask_line" || -z "$api_key_write_line" ]] \
  || ! ((api_key_umask_line < api_key_write_line)); then
  record_failure "App Store Connect API key is not written with restricted permissions"
fi
if ! grep -Eq 'APPLE_KEYCHAIN_PATH=.*GITHUB_ENV' <<<"$import_block"; then
  record_failure "certificate import does not export APPLE_KEYCHAIN_PATH via GITHUB_ENV"
fi
if ! grep -Eq 'APPLE_SIGNING_IDENTITY=.*GITHUB_ENV' <<<"$import_block"; then
  record_failure "certificate import does not export its resolved signing identity via GITHUB_ENV"
fi
if ! grep -Fq "EXPECTED_SIGNING_AUTHORITY: \${{ secrets.APPLE_SIGNING_IDENTITY }}" <<<"$import_block" \
  || ! grep -Fq 'identity_count=' <<<"$import_block"; then
  record_failure "certificate import does not select exactly one configured signing authority"
fi
if ! grep -Fq "security list-keychains -d user > \"\$original_keychains_temp\"" <<<"$import_block" \
  || ! grep -Fq "mv \"\$original_keychains_temp\" \"\$original_keychains_path\"" <<<"$import_block"; then
  record_failure "certificate import does not publish the original keychain list atomically"
fi
umask_line="$(grep -n -m1 -E '^[[:space:]]+umask[[:space:]]+077' <<<"$import_block" | cut -d: -f1 || true)"
certificate_path_line="$(grep -n -m1 -F "certificate_path=\"\$RUNNER_TEMP/certificate.p12\"" <<<"$import_block" | cut -d: -f1 || true)"
certificate_write_line="$(grep -n -m1 -F "base64 --decode > \"\$certificate_path\"" <<<"$import_block" | cut -d: -f1 || true)"
[[ -n "$umask_line" ]] || record_failure "certificate import does not restrict credential file permissions"
[[ -n "$certificate_path_line" ]] || record_failure "certificate import does not target certificate.p12"
[[ -n "$certificate_write_line" ]] || record_failure "certificate import does not decode certificate.p12"
if [[ -n "$umask_line" && -n "$certificate_write_line" ]] \
  && ! ((umask_line < certificate_write_line)); then
  record_failure "certificate import restricts file permissions after writing certificate.p12"
fi
if [[ -n "$certificate_path_line" && -n "$certificate_write_line" ]] \
  && ! ((certificate_path_line < certificate_write_line)); then
  record_failure "certificate import sets the certificate.p12 path after decoding"
fi
for import_command in \
  "security create-keychain" \
  "security import" \
  "security set-key-partition-list" \
  "security list-keychains -d user -s"; do
  if ! grep -Fq "$import_command" <<<"$import_block"; then
    record_failure "certificate import is missing: $import_command"
  fi
done
if ! grep -Fq 'bash tauri/scripts/sign-macos-resources.sh tauri/src-tauri/resources' <<<"$sign_block"; then
  record_failure "native resource signing step does not invoke the signing script"
fi
for signing_block in "$test_block" "$sign_block"; do
  if ! grep -Fq "APPLE_SIGNING_AUTHORITY: \${{ secrets.APPLE_SIGNING_IDENTITY }}" <<<"$signing_block"; then
    record_failure "native signing does not receive the configured Developer ID authority"
  fi
done
if grep -Fq "APPLE_SIGNING_IDENTITY: \${{ secrets.APPLE_SIGNING_IDENTITY }}" <<<"$sign_block"; then
  record_failure "native resource signing step overrides the identity resolved from its keychain"
fi
if ! grep -Eq '^[[:space:]]+if:[[:space:]]+always\(\)' <<<"$cleanup_block"; then
  record_failure "nested-signing cleanup does not run after failures"
fi
if ! grep -Fq 'security delete-keychain' <<<"$cleanup_block"; then
  record_failure "nested-signing cleanup does not delete the ephemeral keychain"
fi
if ! grep -Fq 'security list-keychains -d user -s' <<<"$cleanup_block"; then
  record_failure "nested-signing cleanup does not restore the user keychain search list"
fi
if ! grep -Fq "\"\$RUNNER_TEMP/certificate.p12\"" <<<"$cleanup_block"; then
  record_failure "nested-signing cleanup does not remove certificate.p12"
fi
if ! grep -Fq "\"\$original_keychains_temp\"" <<<"$cleanup_block"; then
  record_failure "nested-signing cleanup does not remove an incomplete keychain-list snapshot"
fi
for notarize_command in \
  'xcrun notarytool submit' \
  "--key \"\$APPLE_API_KEY_PATH\"" \
  "--key-id \"\$APPLE_API_KEY\"" \
  "--issuer \"\$APPLE_API_ISSUER\"" \
  '--wait' \
  'xcrun stapler staple' \
  'xcrun stapler validate' \
  'hdiutil verify' \
  'codesign --verify' \
  'spctl --assess --verbose=4 --type open' \
  '--context context:primary-signature'; do
  if ! grep -Fq -- "$notarize_command" <<<"$notarize_dmg_block"; then
    record_failure "disk-image notarization is missing: $notarize_command"
  fi
done
if ! grep -Eq "^[[:space:]]+if:[[:space:]]+github.ref_type != 'tag'" <<<"$upload_dry_run_block"; then
  record_failure "dry-run artifact upload does not exclude tags"
fi
if ! grep -Eq "^[[:space:]]+if:[[:space:]]+github.ref_type == 'tag'" <<<"$replace_release_dmg_block"; then
  record_failure "release DMG replacement does not require a tag"
fi
if ! grep -Eq "^[[:space:]]+if:[[:space:]]+github.ref_type == 'tag'" <<<"$publish_release_block"; then
  record_failure "release publication does not require a tag"
fi
if ! grep -Fq 'gh release upload' <<<"$replace_release_dmg_block" \
  || ! grep -Fq -- '--clobber' <<<"$replace_release_dmg_block"; then
  record_failure "tagged release does not replace Tauri's pre-notarization DMG asset"
fi
if ! grep -Eq '^[[:space:]]+if:[[:space:]]+always\(\)' <<<"$api_key_cleanup_block" \
  || ! grep -Fq "api_key_path=\"\${APPLE_API_KEY_PATH:-\$RUNNER_TEMP/AuthKey.p8}\"" <<<"$api_key_cleanup_block" \
  || ! grep -Fq "rm -f \"\$api_key_path\"" <<<"$api_key_cleanup_block"; then
  record_failure "notarization API key cleanup is not unconditional"
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

assert_signature_properties() {
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
  if [[ -n "$TEST_SIGNING_AUTHORITY" ]]; then
    if ! grep -Fxq "Authority=$TEST_SIGNING_AUTHORITY" <<<"$signature_details"; then
      record_failure "unexpected signing authority: $candidate"
    fi
    if ! grep -Eq '^Timestamp=' <<<"$signature_details"; then
      record_failure "missing secure timestamp: $candidate"
    fi
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

# V8 JITs on real workloads; without allow-jit a hardened-runtime node
# SIGTRAPs the moment it runs application code (issue #52). Only boolean
# true counts — a present-but-false key disables JIT just the same.
assert_jit_entitlement() {
  local candidate="$1"
  local entitlement_xml
  local jit_value

  if ! entitlement_xml="$(codesign --display --entitlements - --xml "$candidate" 2>/dev/null)"; then
    record_failure "could not inspect entitlements: $candidate"
    return
  fi
  if ! jit_value="$(plutil -extract 'com\.apple\.security\.cs\.allow-jit' raw -expect bool -o - - <<<"$entitlement_xml" 2>/dev/null)" \
    || [[ "$jit_value" != "true" ]]; then
    record_failure "allow-jit entitlement is not boolean true: $candidate"
  fi
}

assert_no_jit_entitlement() {
  local candidate="$1"
  local entitlement_details

  if ! entitlement_details="$(codesign --display --entitlements - "$candidate" 2>&1)"; then
    record_failure "could not inspect entitlements: $candidate"
    return
  fi
  if grep -Fq 'com.apple.security.cs.allow-jit' <<<"$entitlement_details"; then
    record_failure "unexpected allow-jit entitlement: $candidate"
  fi
}

FIXTURE_ROOT="$(mktemp -d)"
RESOURCE_DIR="$FIXTURE_ROOT/resources"
EXECUTABLE_FIXTURE="$RESOURCE_DIR/bin/tool"
NODE_RUNTIME_FIXTURE="$RESOURCE_DIR/bin/node"
NODE_FIXTURE="$RESOURCE_DIR/node_modules/addon.node"
DYLIB_FIXTURE="$RESOURCE_DIR/lib/libfixture.dylib"
SO_FIXTURE="$RESOURCE_DIR/lib/libfixture.so"
TEXT_FIXTURE="$RESOURCE_DIR/bin/plain-text-tool"
EMPTY_RESOURCE_DIR="$FIXTURE_ROOT/empty-resources"
TRAVERSAL_RESOURCE_DIR="$FIXTURE_ROOT/traversal-resources"
UNREADABLE_DIRECTORY="$TRAVERSAL_RESOURCE_DIR/unreadable"
DASH_RESOURCE_DIR="$FIXTURE_ROOT/-resources"
DASH_FIXTURE="$DASH_RESOURCE_DIR/dash-tool"
FALSE_JIT_ENTITLEMENTS="$FIXTURE_ROOT/false-jit.entitlements.plist"
TEST_SIGNING_IDENTITY="${APPLE_SIGNING_IDENTITY:--}"
TEST_SIGNING_AUTHORITY="${APPLE_SIGNING_AUTHORITY:-}"

cleanup() {
  chmod 0700 "$UNREADABLE_DIRECTORY" 2>/dev/null || true
  rm -rf "$FIXTURE_ROOT"
}
trap cleanup EXIT

run_dash_prefixed_resource() (
  cd "$FIXTURE_ROOT"
  APPLE_SIGNING_IDENTITY="$TEST_SIGNING_IDENTITY" \
    APPLE_SIGNING_AUTHORITY="$TEST_SIGNING_AUTHORITY" \
    bash "$SIGN_SCRIPT" -resources
)

mkdir -p \
  "$(dirname "$EXECUTABLE_FIXTURE")" \
  "$(dirname "$NODE_FIXTURE")" \
  "$(dirname "$DYLIB_FIXTURE")" \
  "$EMPTY_RESOURCE_DIR" \
  "$TRAVERSAL_RESOURCE_DIR" \
  "$DASH_RESOURCE_DIR"
cp /usr/bin/true "$EXECUTABLE_FIXTURE"
cp /usr/bin/true "$NODE_RUNTIME_FIXTURE"
cp /usr/bin/true "$NODE_FIXTURE"
cp /usr/bin/true "$DYLIB_FIXTURE"
cp /usr/bin/true "$SO_FIXTURE"
chmod 0755 "$EXECUTABLE_FIXTURE" "$NODE_RUNTIME_FIXTURE"
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
cat >"$FALSE_JIT_ENTITLEMENTS" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>com.apple.security.cs.allow-jit</key>
	<false/>
</dict>
</plist>
PLIST

assert_macho "$EXECUTABLE_FIXTURE"
assert_macho "$NODE_FIXTURE"
assert_macho "$DYLIB_FIXTURE"
assert_macho "$SO_FIXTURE"
if is_macho "$TEXT_FIXTURE"; then
  record_failure "plain-text executable detected as Mach-O: $TEXT_FIXTURE"
fi

if ! APPLE_SIGNING_IDENTITY="$TEST_SIGNING_IDENTITY" \
  APPLE_SIGNING_AUTHORITY="$TEST_SIGNING_AUTHORITY" \
  bash "$SIGN_SCRIPT" "$RESOURCE_DIR"; then
  record_failure "signing valid resource fixtures failed"
fi

assert_signature_properties "$EXECUTABLE_FIXTURE"
assert_signature_properties "$NODE_RUNTIME_FIXTURE"
assert_signature_properties "$NODE_FIXTURE"
assert_signature_properties "$DYLIB_FIXTURE"
assert_signature_properties "$SO_FIXTURE"
assert_jit_entitlement "$NODE_RUNTIME_FIXTURE"
assert_no_jit_entitlement "$EXECUTABLE_FIXTURE"
assert_no_jit_entitlement "$NODE_FIXTURE"
if [[ -n "$TEST_SIGNING_AUTHORITY" ]] \
  && verify_signature \
    "$EXECUTABLE_FIXTURE" \
    "$TEST_SIGNING_IDENTITY" \
    "${TEST_SIGNING_AUTHORITY%?}"; then
  record_failure "truncated signing authority passed production verification"
fi
if codesign --verify --strict "$TEXT_FIXTURE" >/dev/null 2>&1; then
  record_failure "plain-text executable was signed: $TEXT_FIXTURE"
fi

# The exact v0.5.0 regression: node signed with hardened runtime but no
# entitlements must be rejected by production verification.
codesign --force --sign - --options runtime "$NODE_RUNTIME_FIXTURE" 2>/dev/null
if verify_signature "$NODE_RUNTIME_FIXTURE" "-" "" >/dev/null 2>&1; then
  record_failure "node signed without JIT entitlements passed production verification"
fi

# Explicit-false variant: the key being present must not satisfy
# verification — only boolean true lets V8 JIT.
codesign --force --sign - --options runtime \
  --entitlements "$FALSE_JIT_ENTITLEMENTS" "$NODE_RUNTIME_FIXTURE" 2>/dev/null
if verify_signature "$NODE_RUNTIME_FIXTURE" "-" "" >/dev/null 2>&1; then
  record_failure "node signed with allow-jit=false passed production verification"
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
if [[ "$(id -u)" != 0 ]]; then
  assert_command_fails \
    "resource traversal failure did not fail closed" \
    env APPLE_SIGNING_IDENTITY=- bash "$SIGN_SCRIPT" "$TRAVERSAL_RESOURCE_DIR"
else
  echo "SKIP: traversal failure fixture requires a non-root user"
fi

if ! run_dash_prefixed_resource; then
  record_failure "dash-prefixed valid resource directory failed"
else
  assert_signature_properties "$DASH_FIXTURE"
fi

if ((FAILURE_COUNT > 0)); then
  exit 1
fi
echo "PASS: signed nested Mach-O resources with hardened runtime"
