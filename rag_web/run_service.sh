#!/usr/bin/env bash

# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

BASE_DIR="/mnt/c/docker"

if [ -x "/mnt/c/docker/.venv/bin/uvicorn" ]; then
  VENV_BIN="/mnt/c/docker/.venv/bin"
elif [ -x "/mnt/c/Users/PNarayan/.venv/bin/uvicorn" ]; then
  VENV_BIN="/mnt/c/Users/PNarayan/.venv/bin"
else
  echo "uvicorn not found in expected venvs. Install deps and update run_service.sh." >&2
  exit 1
fi

export PATH="${VENV_BIN}:$PATH"
cd "$BASE_DIR"

exec uvicorn rag_web.app:app --host 0.0.0.0 --port 8000
