# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

"""State helpers for loading and resolving repo ids."""

import json
import fnmatch
import difflib
import re
from typing import Dict, List, Optional

from rag_web.config import STATE_PATH


DEFAULT_REPO_ID = "default"
DEFAULT_REPO_DISPLAY_NAME = "default"


def load_state() -> Dict[str, Dict]:
    """Load the ingestion state JSON (or return empty on error)."""
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # pylint: disable=broad-exception-caught
        return {}


def save_state(state: Dict[str, Dict]) -> None:
    """Persist the ingestion state JSON."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _repo_key(collection: str, repo_id: str) -> str:
    return collection + "::" + repo_id


def list_repos(collection: str) -> List[Dict]:
    """List repo metadata for the given collection."""
    state = load_state()
    repos: List[Dict] = []
    prefix = collection + "::"
    for key, value in state.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        repo_id = None
        root = None
        roots = None
        files = None
        last_run_ts = None
        display_name = None

        if isinstance(value, dict):
            repo_id = value.get("repo_id")
            root = value.get("root")
            roots = value.get("roots")
            files = value.get("files")
            last_run_ts = value.get("last_run_ts")
            display_name = value.get("display_name")

        if not repo_id:
            repo_id = key.split("::", 1)[1]

        if not isinstance(roots, list):
            roots = [root] if root else []
        file_count = len(files) if isinstance(files, dict) else 0
        repos.append(
            {
                "repo_id": repo_id,
                "display_name": display_name,
                "root": root,
                "roots": roots,
                "file_count": file_count,
                "last_run_ts": last_run_ts,
            }
        )

    return repos


def get_repo_summary(collection: str, repo_id: str) -> Optional[Dict]:
    """Return repo metadata for the given repo id."""
    for repo in list_repos(collection):
        if repo.get("repo_id") == repo_id:
            return repo
    return None


def repo_exists(collection: str, repo_id: str) -> bool:
    """Return True if the repo id exists in state."""
    return get_repo_summary(collection, repo_id) is not None


def is_display_name_taken(
    collection: str, display_name: str, exclude_repo_id: Optional[str] = None
) -> bool:
    """Return True if display_name is already used by another repo."""
    target = display_name.strip().lower()
    if not target:
        return False
    for repo in list_repos(collection):
        name = repo.get("display_name") or repo.get("repo_id") or ""
        if name.lower() != target:
            continue
        if exclude_repo_id and repo.get("repo_id") == exclude_repo_id:
            continue
        return True
    return False


def update_display_name(collection: str, repo_id: str, display_name: str) -> bool:
    """Update display_name for a repo. Returns False if repo not found."""
    state = load_state()
    key = _repo_key(collection, repo_id)
    if key not in state:
        return False
    entry = state.get(key)
    if not isinstance(entry, dict):
        entry = {"repo_id": repo_id}
    entry["repo_id"] = repo_id
    entry["display_name"] = display_name
    state[key] = entry
    save_state(state)
    return True


def create_repo(collection: str, repo_id: str, display_name: str) -> bool:
    """Create a new repo entry in state. Returns False if repo already exists."""
    state = load_state()
    key = _repo_key(collection, repo_id)
    if key in state:
        return False
    entry = {
        "repo_id": repo_id,
        "display_name": display_name,
        "root": None,
        "roots": [],
        "root_aliases": {},
        "files": {},
        "last_run_ts": None,
    }
    state[key] = entry
    save_state(state)
    return True


def ensure_default_repo(
    collection: str,
    repo_id: str = DEFAULT_REPO_ID,
    display_name: str = DEFAULT_REPO_DISPLAY_NAME,
) -> bool:
    """Ensure the reserved default repo exists."""
    current = load_state()
    key = _repo_key(collection, repo_id)
    existing = current.get(key)
    changed = False

    if isinstance(existing, dict):
        entry = dict(existing)
    else:
        entry = {}
        changed = True

    if entry.get("repo_id") != repo_id:
        entry["repo_id"] = repo_id
        changed = True
    if not entry.get("display_name"):
        entry["display_name"] = display_name
        changed = True
    if "root" not in entry:
        entry["root"] = None
        changed = True
    if not isinstance(entry.get("roots"), list):
        entry["roots"] = []
        changed = True
    if not isinstance(entry.get("root_aliases"), dict):
        entry["root_aliases"] = {}
        changed = True
    if not isinstance(entry.get("files"), dict):
        entry["files"] = {}
        changed = True
    if "last_run_ts" not in entry:
        entry["last_run_ts"] = None
        changed = True

    if key not in current or changed:
        current[key] = entry
        save_state(current)
        return True
    return False


def delete_repo(collection: str, repo_id: str) -> bool:
    """Delete a repo entry from state."""
    state = load_state()
    key = _repo_key(collection, repo_id)
    if key not in state:
        return False
    state.pop(key, None)
    save_state(state)
    return True


def get_repo_entry(collection: str, repo_id: str) -> Optional[Dict]:
    """Return the raw repo entry from state."""
    state = load_state()
    key = _repo_key(collection, repo_id)
    entry = state.get(key)
    if isinstance(entry, dict):
        return entry
    return None


def list_repo_ids(collection: str) -> List[str]:
    """Return unique repo ids for the given collection."""
    state = load_state()
    repo_ids: List[str] = []
    prefix = collection + "::"
    for key, value in state.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        if isinstance(value, dict) and value.get("repo_id"):
            repo_ids.append(str(value["repo_id"]))
        else:
            repo_ids.append(key.split("::", 1)[1])

    seen = set()
    out: List[str] = []
    for repo_id in repo_ids:
        if repo_id not in seen:
            seen.add(repo_id)
            out.append(repo_id)
    return out


def resolve_repo_ids(
    repo_id_arg: Optional[str], collection: str
) -> List[str]:  # pylint: disable=too-many-return-statements
    """Resolve a repo-id pattern to known repo ids."""
    if not repo_id_arg:
        return []

    known = list_repo_ids(collection)
    if not known:
        return [repo_id_arg]

    if repo_id_arg.startswith("re:"):
        pat = repo_id_arg[3:]
        try:
            rx = re.compile(pat)
        except re.error:
            return []
        return [r for r in known if rx.search(r)]

    if any(ch in repo_id_arg for ch in ["*", "?", "["]):
        return [r for r in known if fnmatch.fnmatch(r, repo_id_arg)]

    if repo_id_arg in known:
        return [repo_id_arg]

    sugg = difflib.get_close_matches(repo_id_arg, known, n=5, cutoff=0.6)
    if sugg:
        return [sugg[0]]

    return []
