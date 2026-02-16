# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

"""FastAPI app serving the RAG web GUI and APIs."""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointIdsList

from rag_web import config, groups, parsers, settings_store, state
from rag_web.jobs import JobManager


app = FastAPI(title="RAG Web GUI")
job_manager = JobManager()

STATIC_DIR = config.BASE_DIR / "rag_web" / "static"
MAX_DISPLAY_NAME = 80
MAX_REPO_ID = 80
MAX_GROUP_NAME = 80
DEFAULT_REPO_ID = state.DEFAULT_REPO_ID
DEFAULT_REPO_DISPLAY_NAME = state.DEFAULT_REPO_DISPLAY_NAME
DEFAULT_CHAT_MODEL = "gpt-5-mini"
CHAT_MODEL_SUGGESTIONS = [
    DEFAULT_CHAT_MODEL,
    "gpt-5",
    "gpt-5-nano",
    "gpt-4.1-mini",
]
MODEL_DISCOVERY_CACHE_TTL_SECONDS = 300
MODEL_DISCOVERY_ERROR_CACHE_TTL_SECONDS = 45
_MODEL_DISCOVERY_CACHE: Dict[str, Any] = {
    "fingerprint": "",
    "expires_at": 0.0,
    "models": [],
}
_MODEL_DISCOVERY_LOCK = threading.Lock()

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class AnswerRequest(BaseModel):
    """Request body for /api/answer."""

    question: str = Field(..., min_length=1)
    repo_id: Optional[str] = None
    repo_ids: Optional[List[str]] = None
    repo_groups: Optional[List[str]] = None
    all_repos: bool = False
    top_k: int = 10
    show_sources: bool = True


class IngestRequest(BaseModel):
    """Request body for /api/ingest."""

    path: str = ""
    repo_id: Optional[str] = None
    repo_ids: Optional[List[str]] = None
    repo_groups: Optional[List[str]] = None
    all_repos: bool = False
    delete_missing: bool = False


class RepoCreateRequest(BaseModel):
    """Request body for creating a repo."""

    repo_id: str = Field(..., min_length=1, max_length=MAX_REPO_ID)
    display_name: str = Field(..., min_length=1, max_length=MAX_DISPLAY_NAME)


class RepoRenameRequest(BaseModel):
    """Request body for renaming a repo display name."""

    display_name: str = Field(..., min_length=1, max_length=MAX_DISPLAY_NAME)


class RepoGroupCreateRequest(BaseModel):
    """Request body for creating a repo group."""

    name: str = Field(..., min_length=1, max_length=MAX_GROUP_NAME)
    repo_ids: List[str] = Field(default_factory=list)


class RepoGroupUpdateRequest(BaseModel):
    """Request body for updating a repo group."""

    name: Optional[str] = Field(None, min_length=1, max_length=MAX_GROUP_NAME)
    repo_ids: Optional[List[str]] = None


class OpenAIKeyRequest(BaseModel):
    """Request body for configuring OpenAI API key."""

    api_key: str = Field(..., min_length=1)


class OpenAITestRequest(BaseModel):
    """Request body for testing OpenAI connectivity."""

    api_key: Optional[str] = None
    chat_model: Optional[str] = None


class OpenAIChatModelRequest(BaseModel):
    """Request body for configuring OpenAI chat model."""

    chat_model: str = Field(..., min_length=1)


def _clean_display_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status_code=400, detail="display_name is required")
    if "::" in name:
        raise HTTPException(status_code=400, detail="display_name cannot contain '::'")
    if len(name) > MAX_DISPLAY_NAME:
        raise HTTPException(
            status_code=400, detail=f"display_name must be <= {MAX_DISPLAY_NAME} chars"
        )
    return name


def _clean_repo_id(value: str) -> str:
    repo_id = value.strip()
    if not repo_id:
        raise HTTPException(status_code=400, detail="repo_id is required")
    if "::" in repo_id:
        raise HTTPException(status_code=400, detail="repo_id cannot contain '::'")
    if len(repo_id) > MAX_REPO_ID:
        raise HTTPException(
            status_code=400, detail=f"repo_id must be <= {MAX_REPO_ID} chars"
        )
    return repo_id


def _clean_group_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if "::" in name:
        raise HTTPException(status_code=400, detail="name cannot contain '::'")
    if len(name) > MAX_GROUP_NAME:
        raise HTTPException(
            status_code=400, detail=f"name must be <= {MAX_GROUP_NAME} chars"
        )
    return name


def _group_key(name: str) -> str:
    return name.strip().lower()


def _clean_repo_ids(repo_ids: List[str], collection: str) -> List[str]:
    if not isinstance(repo_ids, list):
        raise HTTPException(status_code=400, detail="repo_ids must be a list")
    cleaned: List[str] = []
    for value in repo_ids:
        if value is None:
            continue
        repo_id = str(value).strip()
        if repo_id:
            cleaned.append(repo_id)
    if not cleaned:
        raise HTTPException(status_code=400, detail="repo_ids cannot be empty")

    seen = set()
    deduped: List[str] = []
    for repo_id in cleaned:
        if repo_id not in seen:
            seen.add(repo_id)
            deduped.append(repo_id)

    known = set(state.list_repo_ids(collection))
    missing = [repo_id for repo_id in deduped if repo_id not in known]
    if missing:
        detail = "unknown repo_ids: " + ", ".join(missing)
        raise HTTPException(status_code=400, detail=detail)
    return deduped


def _stable_point_id(repo_id: str, relpath: str, chunk_id: int) -> int:
    """Return stable 64-bit integer ID matching ingest.py."""
    raw = f"{repo_id}::{relpath}::{chunk_id}"
    digest = hashlib.blake2b(raw.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False)


def _sse_event(event: str, data: Any) -> str:
    """Format an SSE event payload."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _mask_openai_key(api_key: str) -> str:
    """Return a masked key preview for UI display."""
    value = api_key.strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "..." + value[-4:]


def _resolve_openai_key_info() -> Dict[str, Any]:
    """Resolve runtime OpenAI key from settings or environment."""
    settings_key = settings_store.get_openai_api_key()
    if settings_key:
        return {"value": settings_key, "source": "settings", "can_clear": True}

    env_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if env_key and "YOUR_KEY" not in env_key.upper():
        return {"value": env_key, "source": "environment", "can_clear": False}

    return {"value": "", "source": "missing", "can_clear": False}


def _clean_chat_model(value: str) -> str:
    model = value.strip()
    if not model:
        raise HTTPException(status_code=400, detail="chat_model is required")
    if len(model) > 120:
        raise HTTPException(status_code=400, detail="chat_model is too long")
    if any(ch.isspace() for ch in model):
        raise HTTPException(status_code=400, detail="chat_model cannot contain spaces")
    return model


def _resolve_openai_chat_model_info() -> Dict[str, str]:
    """Resolve runtime OpenAI chat model from settings, env, or default."""
    settings_model = settings_store.get_openai_chat_model()
    if settings_model:
        return {"value": settings_model, "source": "settings"}

    env_model = (os.environ.get("OPENAI_CHAT_MODEL") or "").strip()
    if env_model:
        return {"value": env_model, "source": "environment"}

    default_model = (config.OPENAI_CHAT_MODEL or DEFAULT_CHAT_MODEL).strip()
    if not default_model:
        default_model = DEFAULT_CHAT_MODEL
    return {"value": default_model, "source": "default"}


def _openai_key_fingerprint(api_key: str) -> str:
    """Return stable short fingerprint for OpenAI key cache lookup."""
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return digest[:24]


def _extract_model_id(model_item: Any) -> str:
    """Return model id from SDK object or dict."""
    if isinstance(model_item, dict):
        value = model_item.get("id")
    else:
        value = getattr(model_item, "id", "")
    return str(value or "").strip()


def _is_chat_model_candidate(model_id: str) -> bool:
    """Return True when model id is likely chat-completions compatible."""
    model = model_id.strip().lower()
    if not model or not model.startswith("gpt-"):
        return False

    blocked_terms = (
        "embedding",
        "whisper",
        "moderation",
        "image",
        "realtime",
        "tts",
        "transcribe",
        "instruct",
    )
    for term in blocked_terms:
        if term in model:
            return False
    return True


def _fetch_openai_chat_model_ids(openai_api_key: str) -> List[str]:
    """Fetch chat model ids from OpenAI models API."""
    client = OpenAI(api_key=openai_api_key)
    response = client.models.list()
    data = getattr(response, "data", None)
    if isinstance(data, list):
        records = data
    else:
        try:
            records = list(response)
        except Exception:  # pylint: disable=broad-exception-caught
            records = []

    model_ids: List[str] = []
    seen = set()
    for record in records:
        model_id = _extract_model_id(record)
        if not _is_chat_model_candidate(model_id):
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        model_ids.append(model_id)
    model_ids.sort()
    return model_ids


def _discover_openai_chat_models(openai_api_key: str) -> List[str]:
    """Return cached chat model ids discovered from OpenAI, or empty list."""
    api_key = str(openai_api_key or "").strip()
    if not api_key:
        return []

    fingerprint = _openai_key_fingerprint(api_key)
    now = time.time()

    with _MODEL_DISCOVERY_LOCK:
        cached_fingerprint = str(_MODEL_DISCOVERY_CACHE.get("fingerprint") or "")
        cached_expires_at = float(_MODEL_DISCOVERY_CACHE.get("expires_at") or 0)
        cached_models = _MODEL_DISCOVERY_CACHE.get("models") or []
        if cached_fingerprint == fingerprint and cached_expires_at > now:
            return list(cached_models)

    try:
        discovered = _fetch_openai_chat_model_ids(api_key)
    except Exception:  # pylint: disable=broad-exception-caught
        discovered = []

    ttl = (
        MODEL_DISCOVERY_CACHE_TTL_SECONDS
        if discovered
        else MODEL_DISCOVERY_ERROR_CACHE_TTL_SECONDS
    )

    with _MODEL_DISCOVERY_LOCK:
        _MODEL_DISCOVERY_CACHE["fingerprint"] = fingerprint
        _MODEL_DISCOVERY_CACHE["expires_at"] = now + ttl
        _MODEL_DISCOVERY_CACHE["models"] = list(discovered)
    return discovered


def _chat_model_options(current_model: str, openai_api_key: str) -> List[str]:
    """Return de-duplicated chat model options for Settings UI."""
    options: List[str] = []
    seen = set()
    discovered = _discover_openai_chat_models(openai_api_key)
    candidates = (
        [DEFAULT_CHAT_MODEL, current_model]
        + discovered
        + CHAT_MODEL_SUGGESTIONS
        + [config.OPENAI_CHAT_MODEL]
    )
    for value in candidates:
        model = str(value or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        options.append(model)
    return options


def _require_openai_api_key() -> str:
    """Return configured OpenAI key or raise 400 when missing."""
    info = _resolve_openai_key_info()
    value = str(info.get("value") or "").strip()
    if value:
        return value
    raise HTTPException(
        status_code=400,
        detail="OPENAI_API_KEY not configured. Set it in Settings.",
    )


def _build_subprocess_env(
    openai_api_key: str, openai_chat_model: str
) -> Dict[str, str]:
    """Build subprocess env with required OpenAI key and chat model."""
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = openai_api_key
    env["OPENAI_CHAT_MODEL"] = openai_chat_model
    return env


def _run_openai_connection_test(openai_api_key: str, chat_model: str) -> Dict[str, Any]:
    """Run a minimal OpenAI embeddings + chat connectivity test."""
    client = OpenAI(api_key=openai_api_key)

    embed_resp = client.embeddings.create(
        model=config.OPENAI_EMBED_MODEL,
        input=["healthcheck"],
    )
    vector_size = 0
    data = getattr(embed_resp, "data", None)
    if data and len(data) > 0:
        emb = getattr(data[0], "embedding", None)
        if isinstance(emb, list):
            vector_size = len(emb)

    chat_resp = client.chat.completions.create(
        model=chat_model,
        messages=[{"role": "user", "content": "ping"}],
    )
    chat_choices = getattr(chat_resp, "choices", None)
    chat_ok = bool(chat_choices)

    return {
        "embed_model": config.OPENAI_EMBED_MODEL,
        "chat_model": chat_model,
        "embedding_dimensions": vector_size,
        "chat_ok": chat_ok,
    }


def _ensure_default_repo() -> None:
    """Ensure the reserved default repo exists in state."""
    if not config.QDRANT_COLLECTION:
        return
    state.ensure_default_repo(
        config.QDRANT_COLLECTION,
        repo_id=DEFAULT_REPO_ID,
        display_name=DEFAULT_REPO_DISPLAY_NAME,
    )


def _debug_display_path(root: str, relpath: str) -> str:
    """Build a readable full file path for debug output."""
    if root:
        return root.rstrip("/\\") + "/" + relpath.lstrip("/\\")
    return relpath


def _debug_num_chunks(meta: Dict[str, Any]) -> int:
    """Read num_chunks from state metadata safely."""
    try:
        return int(meta.get("num_chunks", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _retrieve_debug_chunks(
    client: QdrantClient,
    repo_id: str,
    relpath_key: str,
    relpath: str,
    expected_chunks: int,
) -> Dict[int, Dict[str, Any]]:
    """Fetch chunk payloads for one file using stable point IDs."""
    ids = [
        _stable_point_id(repo_id, relpath_key, chunk_id)
        for chunk_id in range(expected_chunks)
    ]
    chunk_map: Dict[int, Dict[str, Any]] = {}
    batch_size = 256

    for idx in range(0, len(ids), batch_size):
        batch = ids[idx : idx + batch_size]
        records = client.retrieve(
            collection_name=config.QDRANT_COLLECTION,
            ids=batch,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            payload = getattr(record, "payload", None) or {}
            if not isinstance(payload, dict):
                continue
            chunk_id_value = payload.get("chunk_id")
            try:
                chunk_id = int(chunk_id_value)
            except (TypeError, ValueError):
                continue
            chunk_map[chunk_id] = {
                "chunk_id": chunk_id,
                "text": str(payload.get("text") or ""),
                "path": payload.get("path"),
                "relpath": payload.get("relpath") or relpath,
                "missing": False,
            }
    return chunk_map


@app.get("/")
def index() -> FileResponse:
    """Serve the static index page."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.on_event("startup")
def startup_event() -> None:
    """Ensure required system repo metadata exists at startup."""
    config.ensure_runtime_dirs()
    _ensure_default_repo()


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    """Serve the favicon for browsers that request /favicon.ico."""
    return FileResponse(str(STATIC_DIR / "favicon.png"))


@app.get("/api/health")
def health() -> JSONResponse:
    """Return Qdrant and environment health details."""
    openai_info = _resolve_openai_key_info()
    chat_model_info = _resolve_openai_chat_model_info()
    result: Dict[str, Any] = {
        "ok": True,
        "qdrant_url": config.QDRANT_URL,
        "collection": config.QDRANT_COLLECTION,
        "collection_exists": False,
        "point_count": None,
        "env_loaded": config.ENV_LOADED,
        "state_file_found": config.STATE_PATH.exists(),
        "openai_api_key_set": bool(openai_info.get("value")),
        "openai_api_key_source": openai_info.get("source"),
        "openai_chat_model": chat_model_info.get("value"),
        "openai_chat_model_source": chat_model_info.get("source"),
    }

    if not config.QDRANT_URL or not config.QDRANT_COLLECTION:
        result["ok"] = False
        result["error"] = "QDRANT_URL or QDRANT_COLLECTION missing"
        return JSONResponse(result)

    try:
        client = QdrantClient(url=config.QDRANT_URL)
        collections = client.get_collections().collections
        exists = any(c.name == config.QDRANT_COLLECTION for c in collections)
        result["collection_exists"] = exists
        if exists:
            count = client.count(
                collection_name=config.QDRANT_COLLECTION, exact=True
            ).count
            result["point_count"] = count
        else:
            result["point_count"] = 0
    except Exception as exc:  # pylint: disable=broad-exception-caught
        result["ok"] = False
        result["error"] = str(exc)

    return JSONResponse(result)


@app.get("/api/settings")
def get_settings() -> JSONResponse:
    """Return runtime settings status for UI."""
    info = _resolve_openai_key_info()
    chat_model_info = _resolve_openai_chat_model_info()
    key_value = str(info.get("value") or "")
    chat_model = str(chat_model_info.get("value") or DEFAULT_CHAT_MODEL).strip()
    payload: Dict[str, Any] = {
        "openai_api_key_set": bool(key_value),
        "openai_api_key_masked": _mask_openai_key(key_value),
        "source": info.get("source") or "missing",
        "can_clear": bool(info.get("can_clear")),
        "openai_chat_model": chat_model,
        "openai_chat_model_source": chat_model_info.get("source") or "default",
        "openai_chat_model_options": _chat_model_options(chat_model, key_value),
        "allowed_ingest_roots": [str(root) for root in config.resolve_allowed_roots()],
    }
    return JSONResponse(payload)


@app.post("/api/settings/openai-key")
def set_openai_key(req: OpenAIKeyRequest) -> JSONResponse:
    """Save OpenAI API key in runtime settings."""
    cleaned = req.api_key.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="api_key is required")
    if "YOUR_KEY" in cleaned.upper():
        raise HTTPException(status_code=400, detail="api_key looks like a placeholder")

    settings_store.set_openai_api_key(cleaned)
    info = _resolve_openai_key_info()
    chat_model_info = _resolve_openai_chat_model_info()
    value = str(info.get("value") or "")
    chat_model = str(chat_model_info.get("value") or DEFAULT_CHAT_MODEL).strip()
    return JSONResponse(
        {
            "ok": True,
            "openai_api_key_set": bool(value),
            "openai_api_key_masked": _mask_openai_key(value),
            "source": info.get("source") or "missing",
            "can_clear": bool(info.get("can_clear")),
            "openai_chat_model": chat_model,
            "openai_chat_model_source": chat_model_info.get("source") or "default",
            "openai_chat_model_options": _chat_model_options(chat_model, value),
        }
    )


@app.post("/api/settings/chat-model")
def set_openai_chat_model(req: OpenAIChatModelRequest) -> JSONResponse:
    """Save OpenAI chat model in runtime settings."""
    cleaned = _clean_chat_model(req.chat_model)
    settings_store.set_openai_chat_model(cleaned)
    openai_key_info = _resolve_openai_key_info()
    key_value = str(openai_key_info.get("value") or "")
    info = _resolve_openai_chat_model_info()
    model_value = str(info.get("value") or DEFAULT_CHAT_MODEL).strip()
    return JSONResponse(
        {
            "ok": True,
            "openai_chat_model": model_value,
            "openai_chat_model_source": info.get("source") or "default",
            "openai_chat_model_options": _chat_model_options(model_value, key_value),
        }
    )


@app.delete("/api/settings/openai-key")
def clear_openai_key() -> JSONResponse:
    """Clear saved OpenAI API key."""
    removed = settings_store.clear_openai_api_key()
    info = _resolve_openai_key_info()
    chat_model_info = _resolve_openai_chat_model_info()
    value = str(info.get("value") or "")
    chat_model = str(chat_model_info.get("value") or DEFAULT_CHAT_MODEL).strip()
    return JSONResponse(
        {
            "ok": True,
            "removed": removed,
            "openai_api_key_set": bool(value),
            "openai_api_key_masked": _mask_openai_key(value),
            "source": info.get("source") or "missing",
            "can_clear": bool(info.get("can_clear")),
            "openai_chat_model": chat_model,
            "openai_chat_model_source": chat_model_info.get("source") or "default",
            "openai_chat_model_options": _chat_model_options(chat_model, value),
        }
    )


@app.post("/api/settings/openai-test")
async def test_openai_connection(req: OpenAITestRequest) -> JSONResponse:
    """Validate OpenAI key and model access with a live API call."""
    candidate = ""
    source = "configured"
    chat_model_info = _resolve_openai_chat_model_info()
    chat_model = str(chat_model_info.get("value") or DEFAULT_CHAT_MODEL).strip()
    chat_model_source = str(chat_model_info.get("source") or "default")
    if req.api_key is not None:
        candidate = req.api_key.strip()
        source = "request"
    if req.chat_model is not None:
        chat_model = _clean_chat_model(req.chat_model)
        chat_model_source = "request"

    if candidate and "YOUR_KEY" in candidate.upper():
        raise HTTPException(status_code=400, detail="api_key looks like a placeholder")

    if not candidate:
        candidate = _require_openai_api_key()

    try:
        result = await asyncio.to_thread(
            _run_openai_connection_test, candidate, chat_model
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        detail = str(exc).strip() or "unknown OpenAI error"
        raise HTTPException(
            status_code=502,
            detail="OpenAI connection test failed: " + detail,
        ) from exc

    payload: Dict[str, Any] = {
        "ok": True,
        "source": source,
        "chat_model_source": chat_model_source,
    }
    payload.update(result)
    return JSONResponse(payload)


@app.get("/api/repos")
def repos() -> JSONResponse:
    """List repos from ingestion state."""
    if not config.QDRANT_COLLECTION:
        return JSONResponse({"repos": [], "warning": "QDRANT_COLLECTION missing"})

    _ensure_default_repo()

    if not config.STATE_PATH.exists():
        return JSONResponse({"repos": [], "warning": "state file not found"})

    return JSONResponse({"repos": state.list_repos(config.QDRANT_COLLECTION)})


@app.get("/api/debug/files/{repo_id}")
def debug_files(repo_id: str) -> JSONResponse:
    """List known chunked files for a repo."""
    if not config.QDRANT_COLLECTION:
        raise HTTPException(status_code=500, detail="QDRANT_COLLECTION missing")

    cleaned_repo_id = repo_id.strip()
    if not cleaned_repo_id:
        raise HTTPException(status_code=400, detail="repo_id is required")

    entry = state.get_repo_entry(config.QDRANT_COLLECTION, cleaned_repo_id)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="repo not found")

    files_value = entry.get("files")
    if not isinstance(files_value, dict):
        return JSONResponse({"repo_id": cleaned_repo_id, "files": []})

    files: List[Dict[str, Any]] = []
    for relpath_key, meta in files_value.items():
        if not isinstance(relpath_key, str):
            continue
        if not isinstance(meta, dict):
            continue

        relpath = str(meta.get("relpath") or relpath_key)
        root = str(meta.get("root") or "")
        num_chunks = _debug_num_chunks(meta)
        if num_chunks <= 0:
            continue

        display_path = _debug_display_path(root, relpath)

        files.append(
            {
                "relpath_key": relpath_key,
                "relpath": relpath,
                "root": root,
                "display_path": display_path,
                "num_chunks": num_chunks,
            }
        )

    files.sort(key=lambda item: str(item.get("display_path") or "").lower())
    return JSONResponse({"repo_id": cleaned_repo_id, "files": files})


@app.get("/api/debug/chunks/{repo_id}")
def debug_chunks(repo_id: str, relpath_key: str) -> JSONResponse:
    """Return all chunks for one repo file."""
    if not config.QDRANT_COLLECTION:
        raise HTTPException(status_code=500, detail="QDRANT_COLLECTION missing")
    if not config.QDRANT_URL:
        raise HTTPException(status_code=500, detail="QDRANT_URL missing")

    cleaned_repo_id = repo_id.strip()
    if not cleaned_repo_id:
        raise HTTPException(status_code=400, detail="repo_id is required")
    cleaned_relpath_key = relpath_key.strip()
    if not cleaned_relpath_key:
        raise HTTPException(status_code=400, detail="relpath_key is required")

    entry = state.get_repo_entry(config.QDRANT_COLLECTION, cleaned_repo_id)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="repo not found")

    files_value = entry.get("files")
    if not isinstance(files_value, dict):
        raise HTTPException(status_code=404, detail="file not found")

    meta = files_value.get(cleaned_relpath_key)
    if not isinstance(meta, dict):
        raise HTTPException(status_code=404, detail="file not found")

    relpath = str(meta.get("relpath") or cleaned_relpath_key)
    root = str(meta.get("root") or "")
    display_path = _debug_display_path(root, relpath)
    num_chunks = _debug_num_chunks(meta)
    if num_chunks <= 0:
        return JSONResponse(
            {
                "repo_id": cleaned_repo_id,
                "relpath_key": cleaned_relpath_key,
                "relpath": relpath,
                "display_path": display_path,
                "expected_chunks": 0,
                "missing_chunks": 0,
                "chunks": [],
            }
        )

    try:
        client = QdrantClient(url=config.QDRANT_URL)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        chunk_map = _retrieve_debug_chunks(
            client=client,
            repo_id=cleaned_repo_id,
            relpath_key=cleaned_relpath_key,
            relpath=relpath,
            expected_chunks=num_chunks,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    chunks: List[Dict[str, Any]] = []
    missing_chunks = 0
    for chunk_id in range(num_chunks):
        chunk = chunk_map.get(chunk_id)
        if chunk is None:
            missing_chunks += 1
            chunks.append({"chunk_id": chunk_id, "text": "", "missing": True})
            continue
        chunks.append(chunk)

    return JSONResponse(
        {
            "repo_id": cleaned_repo_id,
            "relpath_key": cleaned_relpath_key,
            "relpath": relpath,
            "display_path": display_path,
            "expected_chunks": num_chunks,
            "missing_chunks": missing_chunks,
            "chunks": chunks,
        }
    )


@app.post("/api/repos")
def create_repo(req: RepoCreateRequest) -> JSONResponse:
    """Create a new repo entry in state."""
    if not config.QDRANT_COLLECTION:
        raise HTTPException(status_code=500, detail="QDRANT_COLLECTION missing")

    repo_id = _clean_repo_id(req.repo_id)
    display_name = _clean_display_name(req.display_name)

    if state.repo_exists(config.QDRANT_COLLECTION, repo_id):
        raise HTTPException(status_code=409, detail="repo_id already exists")
    if state.is_display_name_taken(config.QDRANT_COLLECTION, display_name):
        raise HTTPException(status_code=409, detail="display_name already in use")

    created = state.create_repo(config.QDRANT_COLLECTION, repo_id, display_name)
    if not created:
        raise HTTPException(status_code=409, detail="repo_id already exists")

    summary = state.get_repo_summary(config.QDRANT_COLLECTION, repo_id)
    if summary is None:
        summary = {"repo_id": repo_id, "display_name": display_name, "file_count": 0}
    return JSONResponse(summary)


@app.get("/api/repo-groups")
def repo_groups() -> JSONResponse:
    """List repo groups from repo_groups.json."""
    groups_list = groups.load_repo_groups()
    payload: Dict[str, Any] = {"groups": groups_list}
    if not config.REPO_GROUPS_PATH.exists():
        payload["warning"] = "repo_groups.json not found"
    return JSONResponse(payload)


@app.post("/api/repo-groups")
def create_repo_group(req: RepoGroupCreateRequest) -> JSONResponse:
    """Create a new repo group."""
    if not config.QDRANT_COLLECTION:
        raise HTTPException(status_code=500, detail="QDRANT_COLLECTION missing")

    groups_list = groups.load_repo_groups()
    name = _clean_group_name(req.name)
    existing_names = {
        _group_key(group.get("name") or "")
        for group in groups_list
        if group.get("name")
    }
    if _group_key(name) in existing_names:
        raise HTTPException(status_code=409, detail="group name already exists")

    repo_ids = _clean_repo_ids(req.repo_ids, config.QDRANT_COLLECTION)

    group = {"name": name, "repo_ids": repo_ids}
    groups_list.append(group)
    groups.save_repo_groups(groups_list)
    return JSONResponse(group)


@app.patch("/api/repo-groups/{group_name}")
def update_repo_group(group_name: str, req: RepoGroupUpdateRequest) -> JSONResponse:
    """Rename a repo group and/or update its repos."""
    if not config.QDRANT_COLLECTION:
        raise HTTPException(status_code=500, detail="QDRANT_COLLECTION missing")

    group_name = group_name.strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="group name is required")

    groups_list = groups.load_repo_groups()
    index = None
    for idx, group in enumerate(groups_list):
        if _group_key(group.get("name") or "") == _group_key(group_name):
            index = idx
            break
    if index is None:
        raise HTTPException(status_code=404, detail="group not found")

    current = groups_list[index]
    name = current.get("name") or group_name
    repo_ids = current.get("repo_ids") or []

    if req.name is not None:
        name = _clean_group_name(req.name)
    if req.repo_ids is not None:
        repo_ids = _clean_repo_ids(req.repo_ids, config.QDRANT_COLLECTION)

    existing_names = {
        _group_key(group.get("name") or "")
        for group in groups_list
        if group.get("name")
    }
    if (
        _group_key(name) != _group_key(group_name)
        and _group_key(name) in existing_names
    ):
        raise HTTPException(status_code=409, detail="group name already exists")

    updated = {"name": name, "repo_ids": repo_ids}
    groups_list[index] = updated
    groups.save_repo_groups(groups_list)
    return JSONResponse(updated)


@app.delete("/api/repo-groups/{group_name}")
def delete_repo_group(group_name: str) -> JSONResponse:
    """Delete a repo group."""
    group_name = group_name.strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="group name is required")

    groups_list = groups.load_repo_groups()
    remaining = [
        group
        for group in groups_list
        if _group_key(group.get("name") or "") != _group_key(group_name)
    ]
    if len(remaining) == len(groups_list):
        raise HTTPException(status_code=404, detail="group not found")

    groups.save_repo_groups(remaining)
    return JSONResponse({"ok": True, "name": group_name})


@app.patch("/api/repos/{repo_id}")
def rename_repo(repo_id: str, req: RepoRenameRequest) -> JSONResponse:
    """Rename repo display name in state."""
    if not config.QDRANT_COLLECTION:
        raise HTTPException(status_code=500, detail="QDRANT_COLLECTION missing")

    repo_id = repo_id.strip()
    if not repo_id:
        raise HTTPException(status_code=400, detail="repo_id is required")

    if not state.repo_exists(config.QDRANT_COLLECTION, repo_id):
        raise HTTPException(status_code=404, detail="repo not found")

    display_name = _clean_display_name(req.display_name)
    if state.is_display_name_taken(
        config.QDRANT_COLLECTION, display_name, exclude_repo_id=repo_id
    ):
        raise HTTPException(status_code=409, detail="display_name already in use")

    if not state.update_display_name(config.QDRANT_COLLECTION, repo_id, display_name):
        raise HTTPException(status_code=404, detail="repo not found")

    summary = state.get_repo_summary(config.QDRANT_COLLECTION, repo_id)
    if summary is None:
        summary = {"repo_id": repo_id, "display_name": display_name}
    return JSONResponse(summary)


@app.delete("/api/repos/{repo_id}")
def delete_repo(repo_id: str) -> JSONResponse:
    """Delete repo vectors from Qdrant and remove from state."""
    if not config.QDRANT_COLLECTION:
        raise HTTPException(status_code=500, detail="QDRANT_COLLECTION missing")
    if not config.QDRANT_URL:
        raise HTTPException(status_code=500, detail="QDRANT_URL missing")

    repo_id = repo_id.strip()
    if not repo_id:
        raise HTTPException(status_code=400, detail="repo_id is required")
    if repo_id == DEFAULT_REPO_ID:
        raise HTTPException(status_code=403, detail="default repo cannot be deleted")

    active = job_manager.get_active_job()
    if active and active.status in ("queued", "starting", "running"):
        raise HTTPException(status_code=409, detail="ingest job running")

    if not state.repo_exists(config.QDRANT_COLLECTION, repo_id):
        raise HTTPException(status_code=404, detail="repo not found")

    entry = state.get_repo_entry(config.QDRANT_COLLECTION, repo_id)
    files = None
    if isinstance(entry, dict):
        files = entry.get("files")
        if not isinstance(files, dict):
            files = None

    if files is None:
        raise HTTPException(
            status_code=409,
            detail="repo metadata missing files; re-ingest before deleting",
        )

    deleted_points = 0
    try:
        client = QdrantClient(url=config.QDRANT_URL)
        batch_ids: List[int] = []
        for relpath, meta in files.items():
            if not isinstance(meta, dict):
                continue
            num_chunks = int(meta.get("num_chunks", 0) or 0)
            if num_chunks <= 0:
                continue
            for chunk_id in range(num_chunks):
                batch_ids.append(_stable_point_id(repo_id, relpath, chunk_id))
                deleted_points += 1
                if len(batch_ids) >= 256:
                    client.delete(
                        collection_name=config.QDRANT_COLLECTION,
                        points_selector=PointIdsList(points=batch_ids),
                    )
                    batch_ids = []
        if batch_ids:
            client.delete(
                collection_name=config.QDRANT_COLLECTION,
                points_selector=PointIdsList(points=batch_ids),
            )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not state.delete_repo(config.QDRANT_COLLECTION, repo_id):
        raise HTTPException(status_code=404, detail="repo not found")

    payload: Dict[str, Any] = {
        "ok": True,
        "repo_id": repo_id,
        "deleted_points": deleted_points,
    }
    return JSONResponse(payload)


def _run_answer_sync(cmd: list, env: Dict[str, str]) -> subprocess.CompletedProcess:
    """Run answer.py synchronously in a subprocess."""
    return subprocess.run(
        cmd,
        cwd=str(config.BASE_DIR),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _normalize_ingest_path(raw_path: str) -> str:
    """Normalize ingest path from UI input."""
    path = raw_path.strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in ("'", '"', "`"):
        path = path[1:-1].strip()

    if path.startswith("file:///"):
        path = path[8:]

    win_match = re.match(r"^([a-zA-Z]):[\\/](.*)$", path)
    if win_match:
        drive = win_match.group(1).lower()
        rest = win_match.group(2).replace("\\", "/")
        path = f"/mnt/{drive}/{rest}"

    return path


@app.post("/api/answer")
async def answer(req: AnswerRequest) -> JSONResponse:
    """Run answer.py and parse its stdout."""
    if not config.QDRANT_COLLECTION:
        raise HTTPException(status_code=500, detail="QDRANT_COLLECTION missing")

    if not config.ANSWER_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="answer.py not found")
    openai_api_key = _require_openai_api_key()

    repo_id_args: List[str] = []
    ignored_repo_groups: List[str] = []
    if not req.all_repos:
        if req.repo_ids:
            for repo_id in req.repo_ids:
                if repo_id is None:
                    continue
                value = repo_id.strip()
                if value:
                    repo_id_args.append(value)
        if req.repo_id:
            repo_id_args.append(req.repo_id.strip())
        if req.repo_groups:
            group_map = groups.repo_group_map()
            for group_name in req.repo_groups:
                if group_name is None:
                    continue
                name = str(group_name).strip()
                if not name:
                    continue
                group = group_map.get(_group_key(name))
                if not group:
                    ignored_repo_groups.append(name)
                    continue
                repo_id_args.extend(group.get("repo_ids") or [])

    if repo_id_args:
        seen = set()
        deduped: List[str] = []
        for repo_id in repo_id_args:
            if repo_id not in seen:
                seen.add(repo_id)
                deduped.append(repo_id)
        repo_id_args = deduped

    resolved_repo_ids: List[str] = []
    ignored_repo_ids: List[str] = []
    if repo_id_args:
        seen = set()
        for repo_id in repo_id_args:
            matches = state.resolve_repo_ids(repo_id, config.QDRANT_COLLECTION)
            if not matches:
                ignored_repo_ids.append(repo_id)
                continue
            for match in matches:
                if match not in seen:
                    seen.add(match)
                    resolved_repo_ids.append(match)

    cmd = [
        sys.executable,
        str(config.ANSWER_SCRIPT),
        req.question,
        "--top-k",
        str(req.top_k),
    ]
    if resolved_repo_ids:
        for repo_id in resolved_repo_ids:
            cmd.extend(["--repo-id", repo_id])
    if req.show_sources:
        cmd.append("--show-sources")

    chat_model_info = _resolve_openai_chat_model_info()
    chat_model = str(chat_model_info.get("value") or DEFAULT_CHAT_MODEL).strip()
    env = _build_subprocess_env(openai_api_key, chat_model)
    result = await asyncio.to_thread(_run_answer_sync, cmd, env)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "answer.py failed").strip()
        raise HTTPException(status_code=500, detail=detail)

    parsed = parsers.parse_answer_output(result.stdout)
    parsed["resolved_repo_ids"] = resolved_repo_ids
    parsed["ignored_repo_ids"] = ignored_repo_ids
    parsed["ignored_repo_groups"] = ignored_repo_groups
    return JSONResponse(parsed)


@app.post("/api/ingest")
async def ingest(req: IngestRequest) -> JSONResponse:
    """Start an ingestion job."""
    if not config.INGEST_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="ingest.py not found")

    if not config.QDRANT_COLLECTION:
        raise HTTPException(status_code=500, detail="QDRANT_COLLECTION missing")
    openai_api_key = _require_openai_api_key()

    _ensure_default_repo()

    repo_id_args: List[str] = []
    ignored_repo_groups: List[str] = []
    warnings: List[str] = []

    if req.all_repos:
        repo_id_args = state.list_repo_ids(config.QDRANT_COLLECTION)
        if not repo_id_args:
            raise HTTPException(status_code=400, detail="no repos found")
    else:
        if req.repo_ids:
            for repo_id in req.repo_ids:
                if repo_id is None:
                    continue
                value = str(repo_id).strip()
                if value:
                    repo_id_args.append(value)
        if req.repo_id:
            repo_id_args.append(req.repo_id.strip())
        if req.repo_groups:
            group_map = groups.repo_group_map()
            for group_name in req.repo_groups:
                if group_name is None:
                    continue
                name = str(group_name).strip()
                if not name:
                    continue
                group = group_map.get(_group_key(name))
                if not group:
                    ignored_repo_groups.append(name)
                    continue
                repo_id_args.extend(group.get("repo_ids") or [])

    if ignored_repo_groups:
        warnings.append("ignored repo groups: " + ", ".join(ignored_repo_groups))

    if not repo_id_args:
        raise HTTPException(status_code=400, detail="repo_id is required")

    seen_repo_ids = set()
    repo_ids: List[str] = []
    for repo_id in repo_id_args:
        if repo_id not in seen_repo_ids:
            seen_repo_ids.add(repo_id)
            repo_ids.append(repo_id)

    raw_path = req.path.strip()
    entries: List[Dict[str, List[str]]] = []
    if raw_path:
        target = Path(_normalize_ingest_path(raw_path))
        if not target.exists():
            raise HTTPException(status_code=400, detail="path does not exist")
        if not config.is_path_allowed(target):
            raise HTTPException(status_code=403, detail="path not allowlisted")
        resolved_path = str(target.resolve())
        for repo_id in repo_ids:
            entries.append({"repo_id": repo_id, "paths": [resolved_path]})
    else:
        for repo_id in repo_ids:
            entry = state.get_repo_entry(config.QDRANT_COLLECTION, repo_id)
            if not isinstance(entry, dict):
                warnings.append(f"{repo_id}: repo not found; provide a path to ingest")
                continue
            roots_value = entry.get("roots")
            roots: List[str] = []
            if isinstance(roots_value, list):
                roots = [str(root) for root in roots_value if root]
            primary_root = entry.get("root")
            if primary_root and primary_root not in roots:
                roots.insert(0, primary_root)
            roots = [root for root in roots if root]
            if not roots:
                warnings.append(
                    f"{repo_id}: no recorded roots; provide a path to ingest"
                )
                continue

            missing: List[str] = []
            blocked: List[str] = []
            resolved: List[str] = []
            for root in roots:
                normalized = _normalize_ingest_path(root)
                target = Path(normalized)
                if not target.exists():
                    missing.append(normalized)
                    continue
                if not config.is_path_allowed(target):
                    blocked.append(normalized)
                    continue
                resolved.append(str(target.resolve()))

            if missing:
                warnings.append(f"{repo_id}: missing roots: " + ", ".join(missing))
            if blocked:
                warnings.append(f"{repo_id}: not allowlisted: " + ", ".join(blocked))

            resolved = list(dict.fromkeys(resolved))
            if resolved:
                entries.append({"repo_id": repo_id, "paths": resolved})
            else:
                warnings.append(f"{repo_id}: no valid roots to ingest")

    if not entries:
        detail = "no valid ingest targets found"
        if warnings:
            detail = detail + "; " + "; ".join(warnings[:5])
        raise HTTPException(status_code=400, detail=detail)

    job, busy = await job_manager.start_job(
        entries=entries,
        delete_missing=req.delete_missing,
        openai_api_key=openai_api_key,
    )
    if busy:
        raise HTTPException(status_code=409, detail=busy)
    payload: Dict[str, Any] = {"job_id": job.job_id, "status": "started"}
    if warnings:
        payload["warnings"] = warnings
    return JSONResponse(payload)


@app.get("/api/ingest/{job_id}")
def ingest_status(job_id: str) -> JSONResponse:
    """Return current status for an ingest job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return JSONResponse(job.to_dict())


@app.get("/api/ingest/{job_id}/events")
async def ingest_events(job_id: str, request: Request) -> StreamingResponse:
    """Stream ingest logs via SSE."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_generator():
        idx = 0
        while True:
            if await request.is_disconnected():
                break

            current = job_manager.get_job(job_id)
            if not current:
                yield _sse_event("error", {"error": "job not found"})
                break

            while idx < len(current.logs):
                line = current.logs[idx]
                idx += 1
                yield _sse_event("log", {"line": line})

            if current.status == "done":
                yield _sse_event("done", current.to_dict())
                break

            if current.status == "error":
                payload: Dict[str, Any] = current.to_dict()
                payload["stderr"] = current.stderr[-20:]
                yield _sse_event("error", payload)
                break

            await asyncio.sleep(0.5)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_generator(), media_type="text/event-stream", headers=headers
    )
