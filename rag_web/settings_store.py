# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

"""Persistent runtime settings storage."""

import json
import os
import time
from typing import Any, Dict

from rag_web import config


def _read_settings() -> Dict[str, Any]:
    if not config.SETTINGS_PATH.exists():
        return {}
    try:
        raw = config.SETTINGS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:  # pylint: disable=broad-exception-caught
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _write_settings(data: Dict[str, Any]) -> None:
    config.ensure_runtime_dirs()
    config.SETTINGS_PATH.write_text(
        json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
    )
    try:
        os.chmod(str(config.SETTINGS_PATH), 0o600)
    except Exception:  # pylint: disable=broad-exception-caught
        pass


def get_openai_api_key() -> str:
    """Return the saved OpenAI API key, or empty string."""
    data = _read_settings()
    value = data.get("openai_api_key")
    if value is None:
        return ""
    return str(value).strip()


def has_openai_api_key() -> bool:
    """Return True when a non-empty API key is saved."""
    return bool(get_openai_api_key())


def set_openai_api_key(api_key: str) -> None:
    """Persist OpenAI API key to runtime settings."""
    cleaned = api_key.strip()
    data = _read_settings()
    data["openai_api_key"] = cleaned
    data["updated_ts"] = int(time.time())
    _write_settings(data)


def clear_openai_api_key() -> bool:
    """Remove OpenAI API key from settings. Returns True if removed."""
    data = _read_settings()
    if "openai_api_key" not in data:
        return False
    data.pop("openai_api_key", None)
    data["updated_ts"] = int(time.time())
    _write_settings(data)
    return True
