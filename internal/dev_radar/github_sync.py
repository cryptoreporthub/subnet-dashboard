"""Worker GitHub sync for Dev Pulse velocity scores."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from internal.job_scheduler import cancel_job, schedule_in_seconds

logger = logging.getLogger(__name__)

CACHE_PATH = os.environ.get("DEV_RADAR_CACHE_PATH", os.path.join("data", "dev_radar_cache.json"))
BATCH_SIZE = int(os.environ.get("DEV_RADAR_GITHUB_BATCH", "40"))
REFRESH_MINUTES = int(os.environ.get("DEV_RADAR_GITHUB_REFRESH_MINUTES", "60"))
JOB_ID = "dev-radar-github-sync"

_lock = threading.Lock()
_scheduler: Optional["DevRadarGithubScheduler"] = None


def github_sync_enabled() -> bool:
    return os.environ.get("DEV_RADAR_GITHUB_SYNC", "off").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_github_repo(url: str) -> Optional[Tuple[str, str]]:
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s#?.]+)", str(url or ""), re.I)
    if not m:
        return None
    owner = m.group(1).strip()
    repo = m.group(2).strip().removesuffix(".git")
    if not owner or not repo:
        return None
    return owner, repo


def load_dev_radar_cache(path: Optional[str] = None) -> Dict[str, Any]:
    snap_path = path or CACHE_PATH
    try:
        with open(snap_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_dev_radar_cache(data: Dict[str, Any], path: Optional[str] = None) -> None:
    snap_path = path or CACHE_PATH
    os.makedirs(os.path.dirname(snap_path) or ".", exist_ok=True)
    tmp = f"{snap_path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, snap_path)


def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_repo_commits_7d(owner: str, repo: str) -> Dict[str, Any]:
    """GitHub commits in last 7 days — honest error on rate limit / 404."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits",
            params={"since": since, "per_page": 100},
            headers=_github_headers(),
            timeout=12,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}
    if resp.status_code == 404:
        return {"ok": False, "error": "repo_not_found"}
    if resp.status_code in (403, 429):
        return {"ok": False, "error": "rate_limited"}
    if resp.status_code != 200:
        return {"ok": False, "error": f"http_{resp.status_code}"}
    try:
        commits = resp.json()
    except ValueError:
        return {"ok": False, "error": "invalid_json"}
    if not isinstance(commits, list):
        return {"ok": False, "error": "unexpected_payload"}

    authors: set[str] = set()
    last_push_at = None
    for row in commits:
        if not isinstance(row, dict):
            continue
        commit = row.get("commit") if isinstance(row.get("commit"), dict) else {}
        author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
        email = author.get("email")
        if email:
            authors.add(str(email))
        date = author.get("date")
        if date and (last_push_at is None or str(date) > str(last_push_at)):
            last_push_at = date
    return {
        "ok": True,
        "commits_7d": len(commits),
        "authors_7d": len(authors),
        "last_push_at": last_push_at,
    }


def _percentile_rank(value: float, cohort: List[float]) -> Optional[float]:
    if not cohort:
        return None
    if len(cohort) == 1:
        return 100.0
    below = sum(1 for x in cohort if x < value)
    return round(100.0 * below / len(cohort), 1)


def _recompute_velocity_percentiles(cache: Dict[str, Any]) -> None:
    subnets = cache.get("subnets") if isinstance(cache.get("subnets"), dict) else {}
    commits_vals: List[float] = []
    for row in subnets.values():
        if not isinstance(row, dict):
            continue
        if row.get("commits_7d") is None:
            continue
        try:
            commits_vals.append(float(row["commits_7d"]))
        except (TypeError, ValueError):
            continue
    for key, row in subnets.items():
        if not isinstance(row, dict) or row.get("commits_7d") is None:
            continue
        try:
            commits = float(row["commits_7d"])
        except (TypeError, ValueError):
            row["velocity_score"] = None
            continue
        row["velocity_score"] = _percentile_rank(commits, commits_vals)


def run_github_sync() -> Dict[str, Any]:
    """Sync one batch of github repos into the volume cache."""
    from internal.dev_radar.service import _load_registry_subnets

    registry = _load_registry_subnets()
    candidates = [
        sn
        for sn in registry
        if isinstance(sn, dict) and str(sn.get("github") or "").strip()
    ]
    candidates.sort(key=lambda s: float(s.get("emission") or 0), reverse=True)
    if not candidates:
        return {"ok": True, "synced": 0, "reason": "no_repos"}

    cache = load_dev_radar_cache()
    meta = cache.setdefault("meta", {})
    cursor = int(meta.get("cursor") or 0) % max(len(candidates), 1)
    batch = []
    for i in range(min(BATCH_SIZE, len(candidates))):
        batch.append(candidates[(cursor + i) % len(candidates)])
    meta["cursor"] = (cursor + len(batch)) % len(candidates)

    subnets = cache.setdefault("subnets", {})
    synced = 0
    errors = 0
    for sn in batch:
        netuid = sn.get("netuid", sn.get("id"))
        if netuid is None:
            continue
        parsed = parse_github_repo(str(sn.get("github") or ""))
        if not parsed:
            continue
        owner, repo = parsed
        result = fetch_repo_commits_7d(owner, repo)
        key = str(int(netuid))
        row = subnets.setdefault(key, {})
        if not result.get("ok"):
            row["sync_error"] = result.get("error")
            errors += 1
            continue
        row.update(
            {
                "commits_7d": result.get("commits_7d"),
                "authors_7d": result.get("authors_7d"),
                "last_push_at": result.get("last_push_at"),
                "synced_at": _now_iso(),
            }
        )
        row.pop("sync_error", None)
        synced += 1

    _recompute_velocity_percentiles(cache)
    cache["updated_at"] = _now_iso()
    save_dev_radar_cache(cache)
    return {"ok": True, "synced": synced, "errors": errors, "cursor": meta.get("cursor")}


class DevRadarGithubScheduler:
    def __init__(self) -> None:
        self._running = False
        self._last_result: Dict[str, Any] = {}

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        with _lock:
            if self._running:
                return {"started": False, "reason": "already running"}
            self._running = True
        if immediate:
            threading.Thread(target=self._tick, daemon=True, name="dev-radar-github-tick").start()
        else:
            schedule_in_seconds(JOB_ID, self._tick, max(120.0, REFRESH_MINUTES * 60))
        return {"started": True, "refresh_minutes": REFRESH_MINUTES}

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._running = False
        cancel_job(JOB_ID)
        return {"stopped": True}

    def _tick(self, reschedule: bool = True) -> Dict[str, Any]:
        result = run_github_sync()
        with _lock:
            self._last_result = dict(result)
        if reschedule and self._running:
            schedule_in_seconds(JOB_ID, self._tick, max(300.0, REFRESH_MINUTES * 60))
        return result


def start_dev_radar_github_scheduler(immediate: bool = False) -> Dict[str, Any]:
    if not github_sync_enabled():
        return {"started": False, "reason": "disabled"}
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = DevRadarGithubScheduler()
        sched = _scheduler
    return sched.start(immediate=immediate)
