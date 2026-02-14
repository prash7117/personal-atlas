# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

"""Configuration and path helpers for rag_web."""

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("RAG_DATA_DIR", str(BASE_DIR / "data")))
ENV_PATH = Path(os.environ.get("RAG_ENV_PATH", str(BASE_DIR / ".env")))
LEGACY_STATE_PATH = BASE_DIR / ".rag_ingest_state.json"
LEGACY_LOCK_PATH = BASE_DIR / ".rag_ingest.lock"
LEGACY_REPO_GROUPS_PATH = BASE_DIR / "repo_groups.json"


def _default_state_path() -> Path:
    if LEGACY_STATE_PATH.exists():
        return LEGACY_STATE_PATH
    return DATA_DIR / ".rag_ingest_state.json"


def _default_lock_path() -> Path:
    if LEGACY_LOCK_PATH.exists():
        return LEGACY_LOCK_PATH
    return DATA_DIR / ".rag_ingest.lock"


def _default_repo_groups_path() -> Path:
    if LEGACY_REPO_GROUPS_PATH.exists():
        return LEGACY_REPO_GROUPS_PATH
    return DATA_DIR / "repo_groups.json"


STATE_PATH = Path(os.environ.get("RAG_STATE_PATH", str(_default_state_path())))
LOCK_PATH = Path(os.environ.get("RAG_LOCK_PATH", str(_default_lock_path())))
REPO_GROUPS_PATH = Path(
    os.environ.get("RAG_REPO_GROUPS_PATH", str(_default_repo_groups_path()))
)
SETTINGS_PATH = Path(
    os.environ.get("RAG_SETTINGS_PATH", str(DATA_DIR / "settings.json"))
)

ANSWER_SCRIPT = BASE_DIR / "answer.py"
INGEST_SCRIPT = BASE_DIR / "ingest.py"

ENV_LOADED = load_dotenv(dotenv_path=str(ENV_PATH))

QDRANT_URL = os.environ.get("QDRANT_URL")
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION")
OPENAI_CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4.1-mini")
OPENAI_EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")


def _parse_allowed_roots(raw_value: str) -> List[Path]:
    roots: List[Path] = []
    parts = [part.strip() for part in raw_value.split(",")]
    for part in parts:
        if part:
            roots.append(Path(part))
    return roots


_DEFAULT_ALLOWED_INGEST_ROOTS: List[Path] = [
    Path("/data/input"),
    DATA_DIR / "input",
    BASE_DIR,
]
ALLOWED_INGEST_ROOTS = (
    _parse_allowed_roots(os.environ.get("RAG_ALLOWED_INGEST_ROOTS", ""))
    or _DEFAULT_ALLOWED_INGEST_ROOTS
)


def is_relative_to(path: Path, root: Path) -> bool:
    """Return True if path is within root."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_allowed_roots() -> List[Path]:
    """Resolve and return the allowlisted ingest roots."""
    roots: List[Path] = []
    for root in ALLOWED_INGEST_ROOTS:
        try:
            roots.append(root.resolve())
        except Exception:  # pylint: disable=broad-exception-caught
            roots.append(root)
    return roots


def is_path_allowed(path: Path) -> bool:
    """Validate that the path is under an allowlisted root."""
    try:
        resolved = path.resolve()
    except Exception:  # pylint: disable=broad-exception-caught
        resolved = path
    for root in resolve_allowed_roots():
        if resolved == root or is_relative_to(resolved, root):
            return True
    return False


def ensure_runtime_dirs() -> None:
    """Create directories needed for runtime state files."""
    required_paths = {
        DATA_DIR,
        STATE_PATH.parent,
        LOCK_PATH.parent,
        REPO_GROUPS_PATH.parent,
        SETTINGS_PATH.parent,
    }
    for path in required_paths:
        path.mkdir(parents=True, exist_ok=True)
