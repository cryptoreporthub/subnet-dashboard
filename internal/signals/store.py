"""Append-only signal log with 7-day TTL (Phase L slice 1)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from internal.file_utils import ensure_data_dir, safe_read_json, safe_write_json

SIGNALS_PATH = os.environ.get("SIGNALS_PATH", "data/signals.json")
RETENTION_DAYS = int(os.environ.get("SIGNAL_RETENTION_DAYS", "7"))
EXPERTS = ("quant", "hype", "dark_horse", "technical")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_z() -> str:
    return _utcnow().isoformat().replace("+00:00", "Z")


def _parse_ts(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _default_store() -> Dict[str, Any]:
    return {"updated_at": None, "entries": [], "by_subnet": {}}


class SignalStore:
    """Persist signals in data/signals.json — append-only, indexed by subnet_id."""

    def __init__(self, path: str = SIGNALS_PATH):
        self.path = path
        self._data = _default_store()

    def load(self) -> Dict[str, Any]:
        ensure_data_dir()
        raw = safe_read_json(self.path, _default_store())
        self._data = {
            "updated_at": raw.get("updated_at"),
            "entries": list(raw.get("entries") or []),
            "by_subnet": dict(raw.get("by_subnet") or {}),
        }
        self._prune()
        return self._data

    def _prune(self) -> None:
        cutoff = _utcnow() - timedelta(days=RETENTION_DAYS)
        kept = [
            e
            for e in self._data.get("entries") or []
            if (_parse_ts(str(e.get("timestamp") or "")) or cutoff) >= cutoff
        ]
        self._data["entries"] = kept
        by_subnet: Dict[str, List[str]] = {}
        latest: Dict[str, Dict[str, Any]] = {}
        for entry in kept:
            sid = entry.get("subnet_id")
            if sid is None:
                continue
            key = str(sid)
            ts = str(entry.get("timestamp") or "")
            by_subnet.setdefault(key, []).append(ts)
            prev = latest.get(key)
            if not prev or ts >= str(prev.get("timestamp") or ""):
                latest[key] = entry
        for key in by_subnet:
            by_subnet[key].sort()
        self._data["by_subnet"] = by_subnet
        self._data["latest_by_subnet"] = latest

    def save(self) -> None:
        self._prune()
        self._data["updated_at"] = _utcnow_z()
        payload = {
            "updated_at": self._data["updated_at"],
            "entries": self._data["entries"],
            "by_subnet": self._data.get("by_subnet") or {},
        }
        safe_write_json(self.path, payload)

    @staticmethod
    def _unchanged(prev: Dict[str, Any], nxt: Dict[str, Any]) -> bool:
        return (
            prev.get("signal_type") == nxt.get("signal_type")
            and prev.get("source_expert") == nxt.get("source_expert")
            and prev.get("confidence") == nxt.get("confidence")
        )

    def append_many(self, signals: List[Dict[str, Any]]) -> int:
        """Append changed signals; return count of new log rows."""
        self.load()
        latest = self._data.get("latest_by_subnet") or {}
        added = 0
        for signal in signals:
            entry = dict(signal)
            entry.setdefault("timestamp", _utcnow_z())
            sid = entry.get("subnet_id")
            if sid is not None:
                prev = latest.get(str(sid))
                if prev and self._unchanged(prev, entry):
                    continue
            self._data["entries"].append(entry)
            if sid is not None:
                latest[str(sid)] = entry
            added += 1
        self._data["latest_by_subnet"] = latest
        if added:
            self.save()
        return added

    def latest_all(self) -> List[Dict[str, Any]]:
        self.load()
        rows = list((self._data.get("latest_by_subnet") or {}).values())
        rows.sort(key=lambda r: r.get("subnet_id") or 0)
        return rows

    def query(
        self,
        subnet_id: Optional[int] = None,
        since: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        self.load()
        rows = list(self._data.get("entries") or [])
        if subnet_id is not None:
            rows = [r for r in rows if r.get("subnet_id") == subnet_id]
        if since:
            since_dt = _parse_ts(since)
            if since_dt:
                rows = [
                    r
                    for r in rows
                    if (_parse_ts(str(r.get("timestamp") or "")) or since_dt) >= since_dt
                ]
        rows.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
        return rows[:limit]

    def summary(self) -> Dict[str, Any]:
        self.load()
        latest = self.latest_all()
        buy = sell = neutral = 0
        confidences: List[float] = []
        for row in latest:
            st = row.get("signal_type", "neutral")
            if st == "buy":
                buy += 1
            elif st == "sell":
                sell += 1
            else:
                neutral += 1
            try:
                confidences.append(float(row.get("confidence", 0) or 0))
            except (TypeError, ValueError):
                pass
        return {
            "status": "success",
            "summary": {
                "total_subnets": len(latest),
                "total_signals": len(self._data.get("entries") or []),
                "buy_count": buy,
                "sell_count": sell,
                "neutral_count": neutral,
                "buy_sell_ratio": round(buy / max(sell, 1), 4),
                "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
                "retention_days": RETENTION_DAYS,
                "updated_at": self._data.get("updated_at"),
            },
        }
