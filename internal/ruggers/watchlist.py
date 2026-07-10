"""
Ruggers Watchlist — detect and track wallets that buy subnet alpha then
sell within short windows (6h / 24h / 72h).

Design:
- Ingest buy/sell events keyed by wallet + netuid.
- Pair buys with subsequent sells to compute hold duration.
- Flag wallets whose median hold time falls below configured thresholds.
- Surface active positions so picks can discount rugger-led momentum.
"""

from __future__ import annotations

import json
import os
import statistics
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_CONFIG_PATH = os.environ.get("RUGGERS_CONFIG_PATH", "config/ruggers.json")
DEFAULT_DATA_PATH = os.environ.get("RUGGERS_DATA_PATH", "data/ruggers_watchlist.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _hours_between(start: str, end: str) -> float:
    a = _parse_iso(start)
    b = _parse_iso(end)
    if not a or not b:
        return 0.0
    return max(0.0, (b - a).total_seconds() / 3600.0)


class RuggerWatchlist:
    """Track flip patterns and maintain a rugger risk registry."""

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        data_path: str = DEFAULT_DATA_PATH,
    ):
        self.config_path = config_path
        self.data_path = data_path
        self.config = self._load_config()
        self.data = self._load_data()

    def _load_config(self) -> Dict[str, Any]:
        defaults = {
            "flip_thresholds_hours": [6, 24, 72],
            "min_flip_count": 2,
            "min_tao_notional": 50.0,
            "rugger_risk_threshold": 0.65,
            "alert_before_exit_hours": 2.0,
            "poll_interval_minutes": 15,
            "watchlist_limit": 100,
        }
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    defaults.update(loaded)
            except Exception:
                pass
        return defaults

    def _load_data(self) -> Dict[str, Any]:
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    raw.setdefault("events", [])
                    raw.setdefault("open_positions", {})
                    raw.setdefault("profiles", {})
                    raw.setdefault("flips", [])
                    return raw
            except Exception:
                pass
        return {
            "updated_at": _now_iso(),
            "events": [],
            "open_positions": {},
            "profiles": {},
            "flips": [],
        }

    def _save_data(self) -> None:
        self.data["updated_at"] = _now_iso()
        os.makedirs(os.path.dirname(self.data_path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.data_path) or ".", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.data_path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            with open(self.data_path, "w") as f:
                json.dump(self.data, f, indent=2)

    def _position_key(self, wallet: str, netuid: int) -> str:
        return f"{wallet}:{netuid}"

    def record_event(
        self,
        wallet: str,
        netuid: int,
        side: str,
        amount_tao: float,
        timestamp: Optional[str] = None,
        source: str = "manual",
        tx_hash: Optional[str] = None,
        subnet_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a buy or sell and update flip statistics."""
        side_norm = side.strip().lower()
        if side_norm not in ("buy", "sell", "stake", "unstake"):
            raise ValueError("side must be buy/sell (or stake/unstake)")
        if side_norm in ("stake",):
            side_norm = "buy"
        if side_norm in ("unstake",):
            side_norm = "sell"

        wallet = wallet.strip()
        if not wallet:
            raise ValueError("wallet is required")

        ts = timestamp or _now_iso()
        min_notional = float(self.config.get("min_tao_notional", 50.0))
        if amount_tao < min_notional:
            return {"status": "ignored", "reason": "below_min_notional", "amount_tao": amount_tao}

        event = {
            "wallet": wallet,
            "netuid": int(netuid),
            "side": side_norm,
            "amount_tao": round(float(amount_tao), 4),
            "timestamp": ts,
            "source": source,
            "tx_hash": tx_hash,
            "subnet_name": subnet_name,
        }
        self.data.setdefault("events", []).append(event)

        flip_result = None
        pos_key = self._position_key(wallet, netuid)
        open_positions: Dict[str, Any] = self.data.setdefault("open_positions", {})

        if side_norm == "buy":
            open_positions[pos_key] = {
                "wallet": wallet,
                "netuid": int(netuid),
                "entry_ts": ts,
                "amount_tao": round(float(amount_tao), 4),
                "subnet_name": subnet_name,
            }
        else:
            entry = open_positions.pop(pos_key, None)
            if entry:
                hold_hours = _hours_between(entry.get("entry_ts", ts), ts)
                flip = {
                    "wallet": wallet,
                    "netuid": int(netuid),
                    "subnet_name": subnet_name or entry.get("subnet_name"),
                    "entry_ts": entry.get("entry_ts"),
                    "exit_ts": ts,
                    "hold_hours": round(hold_hours, 2),
                    "amount_tao": round(float(amount_tao), 4),
                    "source": source,
                }
                self.data.setdefault("flips", []).append(flip)
                flip_result = flip
                self._update_profile(wallet, flip)

        self._save_data()
        return {
            "status": "recorded",
            "event": event,
            "flip": flip_result,
            "profile": self.data.get("profiles", {}).get(wallet),
        }

    def _update_profile(self, wallet: str, flip: Dict[str, Any]) -> None:
        profiles: Dict[str, Any] = self.data.setdefault("profiles", {})
        profile = profiles.setdefault(
            wallet,
            {
                "wallet": wallet,
                "flip_count": 0,
                "hold_hours": [],
                "subnets": [],
                "first_seen": flip.get("entry_ts"),
                "last_seen": flip.get("exit_ts"),
                "risk_score": 0.0,
                "avg_hold_hours": None,
                "median_hold_hours": None,
                "min_hold_hours": None,
                "avg_exit_lead_hours": None,
                "tags": [],
            },
        )

        profile["flip_count"] = int(profile.get("flip_count", 0)) + 1
        holds = profile.setdefault("hold_hours", [])
        holds.append(float(flip.get("hold_hours", 0)))
        profile["hold_hours"] = holds[-50:]

        subnets = profile.setdefault("subnets", [])
        nuid = flip.get("netuid")
        if nuid is not None and nuid not in subnets:
            subnets.append(nuid)

        profile["last_seen"] = flip.get("exit_ts")
        profile["avg_hold_hours"] = round(statistics.mean(holds), 2) if holds else None
        profile["median_hold_hours"] = round(statistics.median(holds), 2) if holds else None
        profile["min_hold_hours"] = round(min(holds), 2) if holds else None

        thresholds = [float(t) for t in self.config.get("flip_thresholds_hours", [6, 24, 72])]
        short_flips = sum(1 for h in holds if h <= max(thresholds))
        profile["short_flip_ratio"] = round(short_flips / len(holds), 3) if holds else 0.0

        # Risk: shorter median hold + more flips = higher score
        median = profile["median_hold_hours"] or 72.0
        flip_factor = min(1.0, profile["flip_count"] / max(1, int(self.config.get("min_flip_count", 2))))
        time_factor = max(0.0, 1.0 - (median / 72.0))
        profile["risk_score"] = round(min(1.0, 0.4 * flip_factor + 0.6 * time_factor), 3)

        profile["tags"] = self._classify_profile(profile, thresholds)
        profile["is_rugger"] = profile["risk_score"] >= float(
            self.config.get("rugger_risk_threshold", 0.65)
        ) and profile["flip_count"] >= int(self.config.get("min_flip_count", 2))

        alert_hours = float(self.config.get("alert_before_exit_hours", 2.0))
        if profile["median_hold_hours"] is not None:
            profile["avg_exit_lead_hours"] = round(
                max(0.0, profile["median_hold_hours"] - alert_hours), 2
            )

    def _classify_profile(self, profile: Dict[str, Any], thresholds: List[float]) -> List[str]:
        tags = []
        median = profile.get("median_hold_hours")
        if median is None:
            return tags
        if median <= thresholds[0]:
            tags.append(f"flip_under_{int(thresholds[0])}h")
        elif len(thresholds) > 1 and median <= thresholds[1]:
            tags.append(f"flip_under_{int(thresholds[1])}h")
        elif len(thresholds) > 2 and median <= thresholds[2]:
            tags.append(f"flip_under_{int(thresholds[2])}h")
        if profile.get("flip_count", 0) >= 5:
            tags.append("serial_flipper")
        if profile.get("risk_score", 0) >= float(self.config.get("rugger_risk_threshold", 0.65)):
            tags.append("rugger")
        return tags

    def get_watchlist(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        limit = limit or int(self.config.get("watchlist_limit", 100))
        profiles = list(self.data.get("profiles", {}).values())
        flagged = [p for p in profiles if p.get("is_rugger")]
        flagged.sort(key=lambda p: (p.get("risk_score", 0), p.get("flip_count", 0)), reverse=True)
        return flagged[:limit]

    def get_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        return self.data.get("profiles", {}).get(wallet.strip())

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Wallets on the watchlist that currently hold open positions."""
        alerts = []
        open_positions: Dict[str, Any] = self.data.get("open_positions", {})
        profiles = self.data.get("profiles", {})
        now = datetime.now(timezone.utc)

        for pos in open_positions.values():
            wallet = pos.get("wallet")
            profile = profiles.get(wallet)
            if not profile or not profile.get("is_rugger"):
                continue

            entry_ts = _parse_iso(pos.get("entry_ts"))
            hold_so_far = 0.0
            if entry_ts:
                hold_so_far = (now - entry_ts).total_seconds() / 3600.0

            median_hold = profile.get("median_hold_hours") or 72.0
            alert_before = float(self.config.get("alert_before_exit_hours", 2.0))
            estimated_exit_in = max(0.0, median_hold - hold_so_far)
            urgency = "high" if estimated_exit_in <= alert_before else "medium"

            alerts.append(
                {
                    "wallet": wallet,
                    "netuid": pos.get("netuid"),
                    "subnet_name": pos.get("subnet_name"),
                    "entry_ts": pos.get("entry_ts"),
                    "hold_hours_so_far": round(hold_so_far, 2),
                    "median_hold_hours": median_hold,
                    "estimated_exit_in_hours": round(estimated_exit_in, 2),
                    "risk_score": profile.get("risk_score"),
                    "tags": profile.get("tags", []),
                    "urgency": urgency,
                    "recommendation": "do_not_follow" if urgency == "high" else "exit_before_median",
                }
            )

        alerts.sort(key=lambda a: a.get("estimated_exit_in_hours", 999))
        return alerts

    def get_subnet_risk(self, netuid: int) -> Dict[str, Any]:
        """Aggregate rugger exposure for a subnet."""
        open_positions = self.data.get("open_positions", {})
        profiles = self.data.get("profiles", {})
        ruggers_in = []
        for key, pos in open_positions.items():
            if int(pos.get("netuid", -1)) != int(netuid):
                continue
            wallet = pos.get("wallet")
            profile = profiles.get(wallet)
            if profile and profile.get("is_rugger"):
                ruggers_in.append(
                    {
                        "wallet": wallet,
                        "amount_tao": pos.get("amount_tao"),
                        "entry_ts": pos.get("entry_ts"),
                        "risk_score": profile.get("risk_score"),
                        "median_hold_hours": profile.get("median_hold_hours"),
                    }
                )
        return {
            "netuid": int(netuid),
            "rugger_count": len(ruggers_in),
            "ruggers": ruggers_in,
            "avoid_follow": len(ruggers_in) > 0,
        }

    def discount_score(self, netuid: int, base_score: float) -> Tuple[float, Dict[str, Any]]:
        """Reduce conviction when known ruggers hold a subnet position."""
        risk = self.get_subnet_risk(netuid)
        if not risk.get("ruggers"):
            return base_score, {"adjusted": False, "reason": "no_rugger_exposure"}

        max_risk = max(r.get("risk_score", 0) for r in risk["ruggers"])
        penalty = min(0.35, 0.15 + max_risk * 0.25)
        adjusted = round(max(0.0, base_score * (1.0 - penalty)), 4)
        return adjusted, {
            "adjusted": True,
            "penalty": round(penalty, 3),
            "rugger_count": risk["rugger_count"],
            "max_risk_score": max_risk,
        }

    def summary(self) -> Dict[str, Any]:
        profiles = self.data.get("profiles", {})
        watchlist = self.get_watchlist()
        return {
            "status": "success",
            "updated_at": self.data.get("updated_at"),
            "config": self.config,
            "stats": {
                "total_wallets_tracked": len(profiles),
                "rugger_count": len(watchlist),
                "open_positions": len(self.data.get("open_positions", {})),
                "total_flips": len(self.data.get("flips", [])),
                "total_events": len(self.data.get("events", [])),
            },
            "thresholds_hours": self.config.get("flip_thresholds_hours"),
        }
