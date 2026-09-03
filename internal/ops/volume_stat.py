"""Read-only statistics for the Patch D persistent-volume watch files."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WATCH_FILES = (
    "predictions.json",
    "pick_score_cache.json",
    "pick_scheduler_state.json",
)


def _roots(base_dir: str | os.PathLike[str] | None) -> list[Path]:
    root = Path(base_dir or os.environ.get("DATA_DIR", "data"))
    roots = [root]
    if base_dir is None and os.environ.get("DATA_DIR", "data") != "data":
        roots.append(Path("data"))
    return list(dict.fromkeys(roots))


def _stat_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": False,
        "mtime_iso": None,
        "epoch": None,
        "size": None,
    }
    try:
        info = path.stat()
    except OSError as exc:
        result["error"] = str(exc)
        return result

    result.update(
        {
            "exists": True,
            "mtime_iso": datetime.fromtimestamp(
                info.st_mtime, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "epoch": int(info.st_mtime),
            "size": info.st_size,
        }
    )
    return result


def build_volume_stat(
    *, base_dir: str | os.PathLike[str] | None = None
) -> dict[str, Any]:
    """Return honest, read-only stats for each watched file."""
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    files = [
        _stat_file(root / filename)
        for root in _roots(base_dir)
        for filename in WATCH_FILES
    ]
    return {"checked_at": checked_at, "files": files}
