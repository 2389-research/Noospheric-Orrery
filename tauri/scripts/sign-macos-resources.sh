#!/usr/bin/env bash
# ABOUTME: Signs Mach-O code nested in Tauri bundle resources before app sealing.
# ABOUTME: Verifies each signature and requires hardened runtime for notarization.
set -euo pipefail

is_macho() {
  local candidate="$1"

  file -b -- "$candidate" | grep -q 'Mach-O'
}

verify_signature() {
  local candidate="$1"
  local identity="$2"
  local authority="$3"
  local signature_details

  codesign --verify --strict --verbose=2 "$candidate" || return 1
  signature_details="$(codesign --display --verbose=4 "$candidate" 2>&1)" || return 1
  if ! grep -Eq '^CodeDirectory .*flags=.*runtime' <<<"$signature_details"; then
    echo "missing hardened runtime: $candidate" >&2
    return 1
  fi
  if [[ "$identity" != "-" ]]; then
    if [[ -z "$authority" ]]; then
      echo "APPLE_SIGNING_AUTHORITY is required for Developer ID signing" >&2
      return 1
    fi
    if ! grep -Fxq "Authority=$authority" <<<"$signature_details"; then
      echo "unexpected signing authority: $candidate" >&2
      return 1
    fi
    if ! grep -Eq '^Timestamp=' <<<"$signature_details"; then
      echo "missing secure timestamp: $candidate" >&2
      return 1
    fi
  fi
}

sign_macos_resources() {
  local resource_dir="$1"
  local identity="$2"
  local authority="$3"
  local candidate
  local candidate_list
  local signing_failed=0
  local signed_count=0
  local -a codesign_args

  candidate_list="$(mktemp "${TMPDIR:-/tmp}/orrery-sign-macos.XXXXXX")"
  if ! find "$resource_dir" -type f \
    \( \
      -perm -u+x -o -perm -g+x -o -perm -o+x \
      -o -name '*.node' -o -name '*.dylib' -o -name '*.so' \
    \) \
    -print0 >"$candidate_list"; then
    echo "failed to inspect resource directory: $resource_dir" >&2
    rm -f "$candidate_list"
    return 1
  fi

  while IFS= read -r -d '' candidate; do
    if ! is_macho "$candidate"; then
      continue
    fi

    codesign_args=(codesign --force)
    if [[ -n "${APPLE_KEYCHAIN_PATH:-}" ]]; then
      codesign_args+=(--keychain "$APPLE_KEYCHAIN_PATH")
    fi
    codesign_args+=(
      --sign "$identity"
      --timestamp
      --options runtime
      "$candidate"
    )

    if ! "${codesign_args[@]}"; then
      signing_failed=1
      break
    fi
    if ! verify_signature "$candidate" "$identity" "$authority"; then
      signing_failed=1
      break
    fi
    ((signed_count += 1))
  done <"$candidate_list"
  rm -f "$candidate_list"

  if ((signing_failed != 0)); then
    return 1
  fi
  if ((signed_count == 0)); then
    echo "no Mach-O code found in resource directory: $resource_dir" >&2
    return 1
  fi
}

main() {
  local resource_dir

  if (($# != 1)); then
    echo "usage: $0 RESOURCE_DIRECTORY" >&2
    return 2
  fi
  if [[ -z "${APPLE_SIGNING_IDENTITY:-}" ]]; then
    echo "APPLE_SIGNING_IDENTITY is required" >&2
    return 2
  fi
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "macOS resource signing requires macOS" >&2
    return 2
  fi
  if [[ ! -d "$1" ]]; then
    echo "resource directory does not exist: $1" >&2
    return 2
  fi
  if ! resource_dir="$(cd -- "$1" && pwd -P)"; then
    echo "could not resolve resource directory: $1" >&2
    return 2
  fi

  sign_macos_resources \
    "$resource_dir" \
    "$APPLE_SIGNING_IDENTITY" \
    "${APPLE_SIGNING_AUTHORITY:-}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
