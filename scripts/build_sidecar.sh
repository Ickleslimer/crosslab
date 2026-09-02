#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_TRIPLE="${1:-$(rustc -Vv 2>/dev/null | awk '/host:/ {print $2}' || echo unknown)}"
OUT_DIR="$ROOT/desktop/src-tauri/binaries"
DIST_DIR="$ROOT/dist"

echo "[CrossLab] Building node sidecar with PyInstaller..."
cd "$ROOT"
uv run pyinstaller packaging/crosslab-node.spec --noconfirm --clean
mkdir -p "$OUT_DIR"
BUILT="$DIST_DIR/crosslab-node"
if [[ ! -f "$BUILT" ]]; then
  echo "Expected sidecar binary not found at $BUILT" >&2
  exit 1
fi
DEST="$OUT_DIR/crosslab-node-$TARGET_TRIPLE"
cp "$BUILT" "$DEST"
chmod +x "$DEST"
echo "[CrossLab] Sidecar copied to $DEST"
