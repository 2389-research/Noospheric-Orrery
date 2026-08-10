#!/usr/bin/env bash
# Stage Noospheric-Orrery services, the built frontend, and runtime binaries
# into src-tauri/resources for bundling. Run before `tauri dev` / `tauri build`.
#
# Usage: scripts/stage.sh [--skip-frontend] [--skip-runtimes]
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
# Noospheric-Orrery is now this script's grandparent (tauri/ is a subfolder
# of the Orrery repo itself) rather than a sibling repo checkout. Override
# with ORRERY_DIR if staging from elsewhere (e.g. a standalone checkout).
ORRERY="${ORRERY_DIR:-$HERE/..}"
RES="$HERE/src-tauri/resources"

UV_VERSION="${UV_VERSION:-0.7.13}"
NODE_VERSION="${NODE_VERSION:-22.12.0}"
SIMMER_SDK_REPO="https://github.com/2389-research/simmer-sdk.git"

SKIP_FRONTEND=0
SKIP_RUNTIMES=0
for arg in "$@"; do
  case "$arg" in
    --skip-frontend) SKIP_FRONTEND=1 ;;
    --skip-runtimes) SKIP_RUNTIMES=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 1 ;;
  esac
done

[ -d "$ORRERY/orchestrator" ] || { echo "Noospheric-Orrery not found at $ORRERY (set ORRERY_DIR)" >&2; exit 1; }

echo "==> Staging services from $ORRERY"
rm -rf "$RES/services"
mkdir -p "$RES/services/packages" "$RES/bin"

copy_service() {
  local name="$1"
  mkdir -p "$RES/services/$name"
  cp -r "$ORRERY/$name/src" "$RES/services/$name/src"
  cp "$ORRERY/$name/pyproject.toml" "$ORRERY/$name/uv.lock" "$RES/services/$name/"
  # Runtime data dirs some services read from (e.g. orchestrator/specs)
  for extra in specs; do
    [ -d "$ORRERY/$name/$extra" ] && cp -r "$ORRERY/$name/$extra" "$RES/services/$name/$extra"
  done
  true
}
copy_service orchestrator
copy_service worker
# EVERY package under packages/, not a hand-listed one. The service pyprojects resolve
# these as `{ path = "../packages/<name>" }`, and `uv sync --frozen` at first launch
# reads the STAGED lockfile — so a package the lockfile references but staging skipped
# fails provisioning, which means the app never starts. Adding a path dep used to
# require remembering to edit this line, and nothing checked that you had
# (orchestrator/tests/test_desktop_staging.py now does).
for pkg in "$ORRERY"/packages/*/; do
  [ -f "$pkg/pyproject.toml" ] || continue
  name="$(basename "$pkg")"
  cp -r "$pkg" "$RES/services/packages/$name"
  # Build/test detritus: a stale .venv shadows the provisioned one, and the caches are
  # dead weight inside a signed bundle.
  rm -rf "$RES/services/packages/$name/.venv" \
         "$RES/services/packages/$name/.pytest_cache" 2>/dev/null || true
  echo "    staged package: $name"
done

echo "==> Staging simmer-sdk (worker dependency, not in lockfile)"
if [ -d "$ORRERY/../simmer-sdk/.git" ]; then
  git -C "$ORRERY/../simmer-sdk" archive HEAD | (mkdir -p "$RES/services/simmer-sdk" && tar -x -C "$RES/services/simmer-sdk")
else
  git clone --depth 1 "$SIMMER_SDK_REPO" "$RES/services/simmer-sdk"
  rm -rf "$RES/services/simmer-sdk/.git"
fi

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  UV_TARGET="x86_64-unknown-linux-gnu";  NODE_TARGET="linux-x64" ;;
  Linux-aarch64) UV_TARGET="aarch64-unknown-linux-gnu"; NODE_TARGET="linux-arm64" ;;
  Darwin-arm64)  UV_TARGET="aarch64-apple-darwin";      NODE_TARGET="darwin-arm64" ;;
  Darwin-x86_64) UV_TARGET="x86_64-apple-darwin";       NODE_TARGET="darwin-x64" ;;
  *) echo "unsupported platform" >&2; exit 1 ;;
esac

# Full Node toolchain (node + npm), cached locally. Used both to build the
# frontend (host node may be too old for Next 16) and as the source of the
# bundled `node` binary.
NODE_DIST="node-v$NODE_VERSION-$NODE_TARGET"
NODE_CACHE="$HERE/scripts/.cache/$NODE_DIST"
if [ ! -x "$NODE_CACHE/bin/node" ]; then
  echo "==> Fetching node $NODE_VERSION"
  mkdir -p "$HERE/scripts/.cache"
  curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/$NODE_DIST.tar.gz" \
    | tar -xz -C "$HERE/scripts/.cache"
fi
export PATH="$NODE_CACHE/bin:$PATH"

if [ "$SKIP_FRONTEND" -eq 0 ]; then
  echo "==> Building Next.js frontend (standalone) with node $(node --version)"
  (
    cd "$ORRERY/frontend"
    [ -d node_modules ] || npm install
    NEXT_OUTPUT=standalone \
    NEXT_PUBLIC_AUTH_MODE=noop \
    BACKEND_URL=http://127.0.0.1:8100 \
    npm run build
  )
  rm -rf "$RES/frontend"
  cp -r "$ORRERY/frontend/.next/standalone" "$RES/frontend"
  mkdir -p "$RES/frontend/.next"
  cp -r "$ORRERY/frontend/.next/static" "$RES/frontend/.next/static"
  cp -r "$ORRERY/frontend/public" "$RES/frontend/public"
fi

if [ "$SKIP_RUNTIMES" -eq 0 ]; then
  if [ ! -x "$RES/bin/uv" ]; then
    echo "==> Fetching uv $UV_VERSION"
    curl -fsSL "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$UV_TARGET.tar.gz" \
      | tar -xz -C "$RES/bin" --strip-components=1 "uv-$UV_TARGET/uv"
  fi
  [ -x "$RES/bin/node" ] || cp "$NODE_CACHE/bin/node" "$RES/bin/node"
fi

echo "==> Staged. Contents:"
du -sh "$RES"/* 2>/dev/null
