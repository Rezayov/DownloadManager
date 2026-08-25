#!/usr/bin/env bash
# Build a fast single-file macOS binary of dm.py with Nuitka (via uv, no venv juggling).
#
# Usage:
#   ./build_binary.sh            # build dist/dm
#   ./build_binary.sh --install  # build and replace /opt/homebrew/bin/dm
set -euo pipefail

cd "$(dirname "$0")"

VERSION=$(grep -m1 '^VERSION = ' dm.py | cut -d'"' -f2)
JOBS=$(sysctl -n hw.ncpu)
OUT="dist"

echo "==> Building dm ${VERSION} (${JOBS} jobs)"

uv run --quiet \
  --python 3.13 \
  --with "nuitka" \
  --with "zstandard" \
  --with "requests" \
  --with "rich" \
  --with "pyyaml" \
  -- python -m nuitka \
    --onefile \
    --assume-yes-for-downloads \
    --clang \
    --lto=yes \
    --jobs="${JOBS}" \
    --python-flag=no_site \
    --python-flag=no_asserts \
    --python-flag=no_docstrings \
    --nofollow-import-to=bs4 \
    --onefile-tempdir-spec="{CACHE_DIR}/dm-binary/{VERSION}" \
    --file-version="${VERSION}" \
    --product-name=dm \
    --output-dir="${OUT}" \
    --output-filename=dm \
    --remove-output \
    dm.py

echo "==> Done: ${OUT}/dm"
"${OUT}/dm" --version

if [[ "${1:-}" == "--install" ]]; then
  TARGET="/opt/homebrew/bin/dm"
  echo "==> Installing to ${TARGET}"
  cp "${OUT}/dm" "${TARGET}"
  echo "==> Installed. Warm-start benchmark:"
  command time -h "${TARGET}" --version 2>&1 | tail -1 || true
fi
