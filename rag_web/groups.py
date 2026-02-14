# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

"""Repo group helpers."""

import json
from typing import Dict, List

from rag_web import config


def save_repo_groups(groups: List[Dict]) -> None:
    """Persist repo groups to repo_groups.json."""
    payload = {"groups": groups}
    config.REPO_GROUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.REPO_GROUPS_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def _normalize_groups(raw: object) -> List[Dict]:
    groups: List[Dict] = []
    if isinstance(raw, dict):
        raw_groups = raw.get("groups", [])
    else:
        raw_groups = raw

    if not isinstance(raw_groups, list):
        return groups

    for item in raw_groups:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("id") or "").strip()
        if not name:
            continue
        repo_ids = item.get("repo_ids") or item.get("repos") or []
        if not isinstance(repo_ids, list):
            repo_ids = []
        repo_ids = [str(r).strip() for r in repo_ids if str(r).strip()]
        groups.append(
            {
                "name": name,
                "repo_ids": repo_ids,
            }
        )
    return groups


def load_repo_groups() -> List[Dict]:
    """Load repo groups from repo_groups.json."""
    if not config.REPO_GROUPS_PATH.exists():
        return []
    try:
        raw = json.loads(config.REPO_GROUPS_PATH.read_text(encoding="utf-8"))
    except Exception:  # pylint: disable=broad-exception-caught
        return []
    return _normalize_groups(raw)


def repo_group_map() -> Dict[str, Dict]:
    """Return repo groups keyed by lowercase name."""
    groups = load_repo_groups()
    return {
        group["name"].strip().lower(): group for group in groups if group.get("name")
    }
