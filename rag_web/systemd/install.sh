#!/usr/bin/env bash

# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SERVICE_SRC="/mnt/c/docker/rag_web/systemd/rag-web.service"
SERVICE_DST="/etc/systemd/system/rag-web.service"
LOGROTATE_SRC="/mnt/c/docker/rag_web/systemd/logrotate-rag-web"
LOGROTATE_DST="/etc/logrotate.d/rag-web"

if [ ! -f "$SERVICE_SRC" ]; then
  echo "Missing $SERVICE_SRC" >&2
  exit 1
fi

if [ ! -f "$LOGROTATE_SRC" ]; then
  echo "Missing $LOGROTATE_SRC" >&2
  exit 1
fi

sudo mkdir -p /var/log/rag-web
sudo touch /var/log/rag-web/uvicorn.log
sudo chmod 0640 /var/log/rag-web/uvicorn.log

sudo cp "$SERVICE_SRC" "$SERVICE_DST"
sudo cp "$LOGROTATE_SRC" "$LOGROTATE_DST"
sudo systemctl daemon-reload
sudo systemctl enable rag-web
sudo systemctl restart rag-web || sudo systemctl start rag-web

echo "Installed and started rag-web.service"
