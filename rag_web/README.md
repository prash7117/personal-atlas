# RAG Web GUI (FastAPI + SSE)

A lightweight browser UI for your existing Qdrant + OpenAI RAG scripts (`ingest.py`, `answer.py`).

Licensed under the Apache License, Version 2.0. See `../LICENSE.txt`.

For the simplest install path, use the Docker quick start in `../README.md`.

## Features
- Ask questions with repo-id filtering (exact / glob / regex / fuzzy)
- Trigger ingestion for a directory or single file
- Live ingest logs via SSE (Server-Sent Events)
- List known repos from `.rag_ingest_state.json`
- Health checks (Qdrant reachable, collection exists, point count)
- Safe ingestion: allowlisted roots, one ingest at a time, no secrets sent to browser

## Project layout
```
rag_web/
  app.py
  config.py
  jobs.py
  parsers.py
  state.py
  requirements.txt
  static/
    index.html
    app.js
    styles.css
  README.md
```

## Requirements
- Python (from your WSL venv)
- Qdrant running on Windows Docker and reachable at `http://localhost:6333` from WSL

## Setup
1) Activate your venv

- Preferred (if you create one):
```
python -m venv /mnt/c/docker/.venv
source /mnt/c/docker/.venv/bin/activate
```

- Or use your existing venv:
```
source /mnt/c/Users/PNarayan/.venv/bin/activate
```

2) Install requirements
```
pip install -r /mnt/c/docker/rag_web/requirements.txt
```

3) Ensure `/mnt/c/docker/.env` exists and includes:
```
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=my_rag
OPENAI_API_KEY=...
OPENAI_CHAT_MODEL=gpt-4.1-mini  # optional
```

## Run
From `/mnt/c/docker`:
```
uvicorn rag_web.app:app --host 0.0.0.0 --port 8000 --reload
```

Or use the helper script:
```
/mnt/c/docker/rag_web/run.sh
```

Open in Windows:
```
http://localhost:8000
```

## Autostart on reboot (background)

This sets up a WSL systemd service for the FastAPI app and a Windows Scheduled Task
to start WSL (and Docker Desktop) at login.

### 1) Install the WSL systemd service (inside WSL)
```
/mnt/c/docker/rag_web/systemd/install.sh
```

This installs `/etc/systemd/system/rag-web.service` and enables it.
The service uses `/mnt/c/docker/rag_web/run_service.sh` (no `--reload`).
Re-run this script if you update the service or log rotation config.

Check status:
```
sudo systemctl status rag-web
```

### 2) Create Windows scheduled tasks (from PowerShell)
Open PowerShell **as your Windows user**, then run:
```
PowerShell -ExecutionPolicy Bypass -File C:\docker\rag_web\windows\setup_autostart.ps1
```

Notes:
- The script auto-detects your default WSL distro. Override with `-Distro <name>` if needed.
- This also adds a task to start Docker Desktop at login (disable with `-StartDocker:$false`).
- Two on-demand tasks are created for manual control:
  - `RAG-Stop-RAG`
  - `RAG-Restart-RAG`

Run on demand (PowerShell or CMD):
```
schtasks /run /tn "RAG-Restart-RAG"
schtasks /run /tn "RAG-Stop-RAG"
```

After reboot, visit:
```
http://localhost:8000
```

## Fresh system bootstrap (one command each side)

WSL (installs deps, configures service, optional Docker restart policy if `QDRANT_CONTAINER` is set):
```
QDRANT_CONTAINER=qdrant /mnt/c/docker/rag_web/bootstrap_wsl.sh
```

Windows (creates scheduled tasks, optional Docker restart policy for Qdrant container):
```
PowerShell -ExecutionPolicy Bypass -File C:\docker\rag_web\windows\bootstrap_windows.ps1 -QdrantContainer qdrant
```

If the service does not start:
- Ensure Docker Desktop auto-start is enabled in its settings.
- Run `wsl.exe -d <distro> --exec /bin/true` once to start systemd.

## Logs and rotation
The service writes to:
```
/var/log/rag-web/uvicorn.log
```

Log rotation is installed at `/etc/logrotate.d/rag-web` (daily, 7 files, compressed).

## Allowlisted ingest roots
Configured in `rag_web/config.py`:
- `/mnt/c/code`
- `/mnt/c/Users/PNarayan/OneDrive - Quantum Corporation/Desktop/Quantum`
- `/mnt/c/docker`

Only paths under these roots are accepted by `/api/ingest`.

## API endpoints (summary)
- `GET /api/health`
- `GET /api/repos`
- `POST /api/answer`
- `POST /api/ingest`
- `GET /api/ingest/{job_id}`
- `GET /api/ingest/{job_id}/events` (SSE)

## Notes
- The UI does **not** expose any `.env` secrets to the browser.
- Only one ingest job runs at a time. A lock file is stored at `/mnt/c/docker/.rag_ingest.lock`.
- Sources preview is not available because `answer.py` does not emit chunk text in its stdout.
- If an ingest crashes and the lock file remains, remove it after verifying no ingest process is running.

## Dev checks
If you want to run local checks on backend files:
```
python -m py_compile /mnt/c/docker/rag_web/app.py \
  /mnt/c/docker/rag_web/config.py \
  /mnt/c/docker/rag_web/jobs.py \
  /mnt/c/docker/rag_web/parsers.py \
  /mnt/c/docker/rag_web/state.py

pylint /mnt/c/docker/rag_web/app.py \
  /mnt/c/docker/rag_web/config.py \
  /mnt/c/docker/rag_web/jobs.py \
  /mnt/c/docker/rag_web/parsers.py \
  /mnt/c/docker/rag_web/state.py
```
