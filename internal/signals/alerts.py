"""Alert detection and webhook subscriptions (Phase L)."""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.file_utils import ensure_data_dir, safe_read_json, safe_write_json
from internal.signals.pipeline import price_flash_subnets

logger = logging.getLogger(__name__)

ALERTS_PATH = os.environ.get("ALERTS_PATH", "data/alerts.json")
SUBSCRIPTIONS_PATH = os.environ.get("ALERT_SUBSCRIPTIONS_PATH", "data/alert_subscriptions.json")

WEIGHT_DIVERGENCE_THRESHOLD = float(os.environ.get("ALERT_WEIGHT_DIVERGENCE", "0.3"))
PENDING_PREDICTIONS_THRESHOLD = int(os.environ.get("ALERT_PENDING_PREDICTIONS", "10"))
ACCURACY_FLOOR = float(os.environ.get("ALERT_ACCURACY_FLOOR", "0.25"))
MAX_ALERTS = int(os.environ.get("ALERT_MAX_STORED", "200"))

ALERT_TYPES = (
    "weight_divergence",
    "pending_predictions",
    "accuracy_drop",
    "subnet_price_flash",
    "signal_change",
)


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_alerts() -> Dict[str, Any]:
    return {"updated_at": None, "alerts": []}


def _default_subscriptions() -> Dict[str, Any]:
    return {"updated_at": None, "webhooks": []}


class AlertEngine:
    """Detect threshold breaches and manage webhook subscriptions."""

    def __init__(
        self,
        alerts_path: str = ALERTS_PATH,
        subscriptions_path: str = SUBSCRIPTIONS_PATH,
    ):
        self.alerts_path = alerts_path
        self.subscriptions_path = subscriptions_path

    def load_alerts(self) -> Dict[str, Any]:
        ensure_data_dir()
        return safe_read_json(self.alerts_path, _default_alerts())

    def save_alerts(self, data: Dict[str, Any]) -> None:
        data["updated_at"] = _utcnow_z()
        safe_write_json(self.alerts_path, data)

    def load_subscriptions(self) -> Dict[str, Any]:
        ensure_data_dir()
        return safe_read_json(self.subscriptions_path, _default_subscriptions())

    def save_subscriptions(self, data: Dict[str, Any]) -> None:
        data["updated_at"] = _utcnow_z()
        safe_write_json(self.subscriptions_path, data)

    def subscribe_webhook(self, url: str) -> Dict[str, Any]:
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("webhook url must start with http:// or https://")
        data = self.load_subscriptions()
        hooks = list(data.get("webhooks") or [])
        if url not in hooks:
            hooks.append(url)
        data["webhooks"] = hooks
        self.save_subscriptions(data)
        return {"status": "success", "url": url, "count": len(hooks)}

    def recent_alerts(self, limit: int = 50, active_only: bool = False) -> Dict[str, Any]:
        data = self.load_alerts()
        rows = list(data.get("alerts") or [])
        if active_only:
            rows = [r for r in rows if r.get("active", True)]
        rows.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
        return {
            "status": "success",
            "meta": {"count": len(rows[:limit]), "updated_at": data.get("updated_at")},
            "alerts": rows[:limit],
        }

    def _append_alert(self, alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        data = self.load_alerts()
        alert = dict(alert)
        alert.setdefault("timestamp", _utcnow_z())
        alert.setdefault("active", True)
        alert.setdefault("id", f"{alert.get('alert_type')}-{alert.get('timestamp')}")

        # Dedupe: skip if same type+key within last hour for system alerts
        key = alert.get("dedupe_key") or alert.get("alert_type")
        for existing in reversed(data.get("alerts") or []):
            if existing.get("dedupe_key") == key and existing.get("alert_type") == alert.get("alert_type"):
                if existing.get("active"):
                    return None
                break

        data.setdefault("alerts", []).append(alert)
        data["alerts"] = data["alerts"][-MAX_ALERTS:]
        self.save_alerts(data)
        self._dispatch_webhooks(alert)
        return alert

    def _dispatch_webhooks(self, alert: Dict[str, Any]) -> None:
        subs = self.load_subscriptions().get("webhooks") or []
        if not subs:
            return
        payload = json.dumps({"alert": alert}).encode("utf-8")

        def _post(url: str) -> None:
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                logger.warning("Webhook dispatch failed for %s: %s", url, exc)

        for url in subs:
            threading.Thread(target=_post, args=(url,), daemon=True).start()

    def check_system_alerts(self) -> List[Dict[str, Any]]:
        """Run all threshold checks; return newly created alerts."""
        created: List[Dict[str, Any]] = []

        # Weight divergence
        try:
            from internal.council.weights import load_weights

            weights = load_weights()
            vals = [float(weights.get(k, 1.0) or 1.0) for k in ("quant", "hype", "dark_horse", "technical")]
            spread = max(vals) - min(vals)
            if spread > WEIGHT_DIVERGENCE_THRESHOLD:
                alert = self._append_alert(
                    {
                        "alert_type": "weight_divergence",
                        "severity": "warning",
                        "message": f"Expert weight spread {spread:.2f} exceeds {WEIGHT_DIVERGENCE_THRESHOLD}",
                        "details": {"weights": weights, "spread": round(spread, 4)},
                        "dedupe_key": "weight_divergence",
                    }
                )
                if alert:
                    created.append(alert)
        except Exception as exc:
            logger.warning("Weight divergence check failed: %s", exc)

        # Pending predictions
        try:
            from internal.learning.predictions_store import load_predictions

            stats = load_predictions().get("stats") or {}
            pending = int(stats.get("pending", 0) or 0)
            if pending > PENDING_PREDICTIONS_THRESHOLD:
                alert = self._append_alert(
                    {
                        "alert_type": "pending_predictions",
                        "severity": "warning",
                        "message": f"{pending} pending predictions (threshold {PENDING_PREDICTIONS_THRESHOLD})",
                        "details": {"pending": pending, "threshold": PENDING_PREDICTIONS_THRESHOLD},
                        "dedupe_key": "pending_predictions",
                    }
                )
                if alert:
                    created.append(alert)
        except Exception as exc:
            logger.warning("Pending predictions check failed: %s", exc)

        # Accuracy drop
        try:
            from internal.learning.predictions_store import load_predictions

            stats = load_predictions().get("stats") or {}
            correct = int(stats.get("correct", 0) or 0)
            wrong = int(stats.get("wrong", 0) or 0)
            resolved = correct + wrong
            accuracy = float(stats.get("accuracy", 0) or 0)
            if resolved >= 10 and accuracy < ACCURACY_FLOOR:
                alert = self._append_alert(
                    {
                        "alert_type": "accuracy_drop",
                        "severity": "critical",
                        "message": f"Learning accuracy {accuracy:.1%} below {ACCURACY_FLOOR:.0%}",
                        "details": {
                            "accuracy": accuracy,
                            "correct": correct,
                            "wrong": wrong,
                            "threshold": ACCURACY_FLOOR,
                        },
                        "dedupe_key": "accuracy_drop",
                    }
                )
                if alert:
                    created.append(alert)
        except Exception as exc:
            logger.warning("Accuracy check failed: %s", exc)

        # Subnet price flash
        for flash in price_flash_subnets():
            alert = self._append_alert(
                {
                    "alert_type": "subnet_price_flash",
                    "severity": "info",
                    "message": f"SN{flash['subnet_id']} {flash.get('name')} moved {flash['price_change_24h']:+.1f}% in 24h",
                    "details": flash,
                    "dedupe_key": f"price_flash_{flash['subnet_id']}",
                }
            )
            if alert:
                created.append(alert)

        return created

    def record_signal_changes(self, changed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Emit alerts when persisted signals change type."""
        created: List[Dict[str, Any]] = []
        for sig in changed:
            alert = self._append_alert(
                {
                    "alert_type": "signal_change",
                    "severity": "info",
                    "message": f"SN{sig.get('subnet_id')} signal → {sig.get('signal_type')} ({sig.get('source_expert')})",
                    "details": sig,
                    "dedupe_key": f"signal_{sig.get('subnet_id')}_{sig.get('signal_type')}",
                }
            )
            if alert:
                created.append(alert)
        return created
