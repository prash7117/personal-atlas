# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

# Personal RAG Assistant
A self-hosted personal AI knowledge assistant and AI search tool. PersonalAtlas ingests documents, indexes them using Qdrant, and provides a web-based interface to ask questions and receive grounded answers strictly based on your own data.

Docker-first personal assistant with:
- FastAPI web UI (`rag_web`)
- Qdrant vector store
- Local ingestion (`ingest.py`)
- Retrieval + answer flow (`answer.py`)

## Quick Start (Recommended)

1. Install Docker Desktop.
2. Clone this repository.
3. From repository root, start services:

```bash
docker compose up -d --build
```

4. Open:

```
http://localhost:8000
```

5. First launch prompts for OpenAI key in a setup modal.
6. Add files to ingest under:

```
./data/input
```

That folder is mounted in the app container as `/data/input`.

## Minimal User Workflow

1. Go to **Settings**, save OpenAI API key, and run **Test connection**.
2. Go to **Ingest** and use path `/data/input`.
3. Go to **Ask** and query your ingested content.

## Persisted Data

- Qdrant vectors: Docker volume `qdrant_data`
- App runtime state/settings: Docker volume `app_data`
- User files to ingest: host folder `./data/input`

## Stop / Start

```bash
docker compose stop
docker compose start
```

## Upgrade

```bash
docker compose pull
docker compose up -d --build
```

## Configuration

Optional overrides can be set in shell or `.env` used by Docker Compose:
- `QDRANT_COLLECTION`
- `OPENAI_CHAT_MODEL`
- `OPENAI_EMBED_MODEL`

You usually do not need to set `OPENAI_API_KEY` in env because the UI Settings tab stores it.
