#!/usr/bin/env bash

# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

cd /mnt/c/docker

exec uvicorn rag_web.app:app --host 0.0.0.0 --port 8000 --reload
