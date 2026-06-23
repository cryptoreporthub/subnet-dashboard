"""
File utilities for safe file operations in serverless environments.

Ensures data directory exists before file writes to prevent
"No such file or directory" errors on Fly.io and similar platforms.
"""

import json
import os
import tempfile
from typing import Any, Dict, Optional


DATA_DIR = os.environ.get("DATA_DIR", "data")


def ensure_data_dir() -> str:
    """Ensure the data directory exists and return its path."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


def safe_write_json(path: str, data: Dict[str, Any]) -> None:
    """
    Write JSON data to a file atomically with directory creation.

    Creates parent directories if they don't exist, then writes
    to a unique temp file (via mkstemp) and renames for atomicity.
    Using mkstemp avoids race conditions when gunicorn workers share
    a common .tmp filename.
    """
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(dir=dir_name or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def safe_read_json(path: str, default: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Read JSON from a file, returning default if missing or invalid.
    """
    if default is None:
        default = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default