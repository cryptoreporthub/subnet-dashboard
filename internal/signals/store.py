"""Append-only signal log with TTL cleanup (Phase L)."""

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
    return {"updated_at": None, "entries": [], "latest_by_subnet": {}}


class SignalStore:
    """Persist signals in data/signals.json (append-only, 7-day TTL)."""

    def __init__(self, path: str = SIGNALS_PATH):
        self.path = path
        self._data = _default_store()

    def load(self) -> Dict[str, Any]:
        ensure_data_dir()
        raw = safe_read_json(self.path, _default_store())
        self._data = {
            "updated_at": raw.get("updated_at"),
            "entries": list(raw.get("entries") or []),
            "latest_by_subnet": dict(raw.get("latest_by_subnet") or {}),
        }
        self._prune()
        return self._data

    def _prune(self) -> None:
        cutoff = _utcnow() - timedelta(days=RETENTION_DAYS)
        kept: List[Dict[str, Any]] = []
        for entry in self._data.get("entries") or []:
            ts = _parse_ts(str(entry.get("timestamp") or ""))
            if ts is None or ts >= cutoff:
                kept.append(entry)
        self._data["entries"] = kept

        latest: Dict[str, Any] = {}
        for entry in kept:
            sid = entry.get("subnet_id")
            if sid is None:
                continue
            key = str(sid)
            prev = latest.get(key)
            if not prev or str(entry.get("timestamp", "")) >= str(prev.get("timestamp", "")):
                latest[key] = entry
        self._data["latest_by_subnet"] = latest

    def save(self) -> None:
        self._prune()
        self._data["updated_at"] = _utcnow_z()
        safe_write_json(self.path, self._data)

    def append(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        self.load()
        entry = dict(signal)
        entry.setdefault("timestamp", _utcnow_z())
        sid = entry.get("subnet_id")
        if sid is not None:
            key = str(sid)
            prev = self._data["latest_by_subnet"].get(key)
            if prev and self._same_signal(prev, entry):
                return prev
        self._data["entries"].append(entry)
        if sid is not None:
            self._data["latest_by_subnet"][str(sid)] = entry
        self.save()
        return entry

    def append_many(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        self.load()
        changed: List[Dict[str, Any]] = []
        for signal in signals:
            entry = dict(signal)
            entry.setdefault("timestamp", _utcnow_z())
            sid = entry.get("subnet_id")
            if sid is not None:
                key = str(sid)
                prev = self._data["latest_by_subnet"].get(key)
                if prev and self._same_signal(prev, entry):
                    continue
            self._data["entries"].append(entry)
            if sid is not None:
                self._data["latest_by_subnet"][str(sid)] = entry
            changed.append(entry)
        if changed:
            self.save()
        return changed

    @staticmethod
    def _same_signal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        keys = ("signal_type", "source_expert", "confidence")
        return all(a.get(k) == b.get(k) for k in keys)

    def latest_all(self) -> List[Dict[str, Any]]:
        self.load()
        rows = list(self._data.get("latest_by_subnet", {}).values())
        rows.sort(key=lambda r: (r.get("subnet_id") is None, r.get("subnet_id", 0)))
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
        by_expert: Dict[str, int] = {e: 0 for e in EXPERTS}
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
            expert = row.get("source_expert")
            if expert in by_expert:
                by_expert[expert] += 1
        total = len(latest) or 1
        return {
            "status": "success",
            "summary": {
                "total_subnets": len(latest),
                "buy_count": buy,
                "sell_count": sell,
                "neutral_count": neutral,
                "buy_sell_ratio": round(buy / max(sell, 1), 4),
                "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
                "by_expert": by_expert,
                "retention_days": RETENTION_DAYS,
                "log_entries": len(self._data.get("entries") or []),
                "updated_at": self._data.get("updated_at"),
            },
        }
