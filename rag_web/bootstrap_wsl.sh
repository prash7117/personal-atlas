#!/usr/bin/env bash

# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

BASE_DIR="/mnt/c/docker"
REQ_FILE="$BASE_DIR/rag_web/requirements.txt"
INSTALL_SCRIPT="$BASE_DIR/rag_web/systemd/install.sh"

if [ ! -f "$REQ_FILE" ]; then
  echo "Missing $REQ_FILE" >&2
  exit 1
fi

if [ -x "$BASE_DIR/.venv/bin/python" ]; then
  VENV="$BASE_DIR/.venv"
elif [ -x "/mnt/c/Users/PNarayan/.venv/bin/python" ]; then
  VENV="/mnt/c/Users/PNarayan/.venv"
else
  VENV="$BASE_DIR/.venv"
  echo "Creating venv at $VENV"
  python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/pip" install -r "$REQ_FILE"

if [ -x "$INSTALL_SCRIPT" ]; then
  "$INSTALL_SCRIPT"
else
  echo "Missing $INSTALL_SCRIPT" >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1; then
  if [ -n "${QDRANT_CONTAINER:-}" ]; then
    docker update --restart unless-stopped "$QDRANT_CONTAINER" || true
  fi
fi

echo "WSL bootstrap complete."
