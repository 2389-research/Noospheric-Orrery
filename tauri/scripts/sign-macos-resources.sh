#!/usr/bin/env bash
# ABOUTME: Signs Mach-O code nested in Tauri bundle resources before app sealing.
# ABOUTME: Verifies each signature and requires hardened runtime for notarization.
set -euo pipefail

is_macho() {
  local candidate="$1"

  file -b -- "$candidate" | grep -q 'Mach-O'
}

sign_macos_resources() {
  local resource_dir="$1"
  local identity="$2"
  local candidate
  local signed_count=0
  local -a codesign_args

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

    "${codesign_args[@]}"
    codesign --verify --strict --verbose=2 "$candidate"
    ((signed_count += 1))
  done < <(
    find "$resource_dir" -type f \
      \( \
        -perm -u+x -o -perm -g+x -o -perm -o+x \
        -o -name '*.node' -o -name '*.dylib' -o -name '*.so' \
      \) \
      -print0
  )

  if ((signed_count == 0)); then
    echo "no Mach-O code found in resource directory: $resource_dir" >&2
    return 1
  fi
}

main() {
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

  sign_macos_resources "$1" "$APPLE_SIGNING_IDENTITY"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
