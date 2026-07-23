"""
Whale Intelligence Service

Tracks wallet behavior across six dimensions:

1. **Ruggers** — fast flippers to avoid (sell within 6h/24h/72h)
2. **Alpha Whales** — highest win-rate + return % on closed trades
3. **Market Movers** — largest price impact on small/mid-cap subnets
4. **Early Movers** — enter before major moves (leading indicator)
5. **Conviction Holders** — long holds with positive outcomes (smart money)
6. **Rotators** — systematic cross-subnet capital rotation

All dimensions share one event ledger and per-wallet profile store.
"""

from __future__ import annotations

import json
import os
import statistics
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.whales.classifiers import classify_wallet, score_dimensions

DEFAULT_CONFIG_PATH = os.environ.get("WHALES_CONFIG_PATH", "config/whales.json")
DEFAULT_DATA_PATH = os.environ.get("WHALES_DATA_PATH", "data/whale_intelligence.json")

TRACKING_DIMENSIONS = [
    "ruggers",
    "alpha_whales",
    "market_movers",
    "early_movers",
    "conviction_holders",
    "rotators",
]


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


def _return_pct(entry_price: Optional[float], exit_price: Optional[float]) -> Optional[float]:
    if entry_price and exit_price and entry_price > 0:
        return round((exit_price - entry_price) / entry_price * 100.0, 2)
    return None


def _short_ss58(wallet: str, head: int = 4, tail: int = 4) -> str:
    w = (wallet or "").strip()
    if len(w) <= head + tail + 1:
        return w
    return f"{w[:head]}…{w[-tail:]}"


def _fmt_tao(amount: float) -> str:
    if amount >= 100:
        return f"{amount:,.0f}"
    if amount >= 10:
        return f"{amount:,.1f}"
    return f"{amount:,.2f}"


def _day_whale_chip(row: Dict[str, Any], *, include_slip: bool) -> str:
    side = str(row.get("side") or "buy")
    amt = _fmt_tao(float(row.get("amount_tao") or 0))
    short = row.get("wallet_short") or _short_ss58(str(row.get("wallet") or ""))
    base = f"Day whale · {amt}τ {side} · {short}"
    slip = row.get("slip_pct")
    if include_slip and slip is not None:
        return f"{base} · ~{float(slip):.2f}% float"
    return base


def _slip_day_chip(row: Dict[str, Any]) -> str:
    side = str(row.get("side") or "buy")
    amt = _fmt_tao(float(row.get("amount_tao") or 0))
    short = row.get("wallet_short") or _short_ss58(str(row.get("wallet") or ""))
    slip = row.get("slip_pct")
    if slip is not None:
        return f"Biggest slip · ~{float(slip):.2f}% float · {amt}τ {side} · {short}"
    return f"Biggest slip · {amt}τ {side} · {short}"


class WhaleIntelligenceService:
    """Central whale tracking service with multi-dimensional leaderboards."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        data_path: Optional[str] = None,
    ):
        self.config_path = config_path or os.environ.get("WHALES_CONFIG_PATH", "config/whales.json")
        self.data_path = data_path or os.environ.get("WHALES_DATA_PATH", "data/whale_intelligence.json")
        self.config = self._load_config()
        self.data = self._load_data()

    def _load_config(self) -> Dict[str, Any]:
        defaults = {
            "flip_thresholds_hours": [6, 24, 72],
            "min_flip_count": 2,
            "min_tao_notional": 50.0,
            "rugger_risk_threshold": 0.65,
            "alert_before_exit_hours": 2.0,
            "small_cap_stake_threshold_tao": 400000,
            "small_cap_max_market_cap_rank": 80,
            "alpha_min_closed_trades": 3,
            "alpha_min_win_rate": 0.55,
            "market_mover_min_impact_score": 0.4,
            "early_mover_horizon_hours": 24,
            "early_mover_min_move_pct": 8.0,
            "conviction_min_hold_hours": 72,
            "rotator_min_subnets": 4,
            "rotator_window_days": 30,
            "leaderboard_limit": 50,
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
                    for key in ("events", "open_positions", "profiles", "closed_trades"):
                        raw.setdefault(key, [] if key != "open_positions" else {})
                    if isinstance(raw.get("profiles"), list):
                        raw["profiles"] = {}
                    return raw
            except Exception:
                pass
        return {
            "updated_at": _now_iso(),
            "events": [],
            "open_positions": {},
            "profiles": {},
            "closed_trades": [],
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
        entry_price: Optional[float] = None,
        exit_price: Optional[float] = None,
        market_cap_rank: Optional[int] = None,
        total_stake_tao: Optional[float] = None,
        price_change_after_hours: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Record a buy/sell event and update wallet intelligence."""
        side_norm = side.strip().lower()
        if side_norm in ("stake",):
            side_norm = "buy"
        elif side_norm in ("unstake",):
            side_norm = "sell"
        if side_norm not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")

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
            "entry_price": entry_price,
            "exit_price": exit_price,
            "market_cap_rank": market_cap_rank,
            "total_stake_tao": total_stake_tao,
            "price_change_after_hours": price_change_after_hours,
        }
        self.data.setdefault("events", []).append(event)

        closed_trade = None
        pos_key = self._position_key(wallet, netuid)
        open_positions: Dict[str, Any] = self.data.setdefault("open_positions", {})

        if side_norm == "buy":
            open_positions[pos_key] = {
                "wallet": wallet,
                "netuid": int(netuid),
                "entry_ts": ts,
                "amount_tao": round(float(amount_tao), 4),
                "subnet_name": subnet_name,
                "entry_price": entry_price,
                "market_cap_rank": market_cap_rank,
                "total_stake_tao": total_stake_tao,
            }
        else:
            entry = open_positions.pop(pos_key, None)
            if entry:
                hold_hours = _hours_between(entry.get("entry_ts", ts), ts)
                ep = entry.get("entry_price") or entry_price
                xp = exit_price
                ret = _return_pct(ep, xp)
                stake = float(entry.get("total_stake_tao") or total_stake_tao or 0)
                amt = float(entry.get("amount_tao") or amount_tao)
                impact = self._compute_impact_score(amt, stake, market_cap_rank or entry.get("market_cap_rank"))
                closed_trade = {
                    "wallet": wallet,
                    "netuid": int(netuid),
                    "subnet_name": subnet_name or entry.get("subnet_name"),
                    "entry_ts": entry.get("entry_ts"),
                    "exit_ts": ts,
                    "hold_hours": round(hold_hours, 2),
                    "amount_tao": round(amt, 4),
                    "entry_price": ep,
                    "exit_price": xp,
                    "return_pct": ret,
                    "won": ret > 0 if ret is not None else None,
                    "market_cap_rank": market_cap_rank or entry.get("market_cap_rank"),
                    "impact_score": impact,
                    "price_change_after_entry": price_change_after_hours,
                    "source": source,
                }
                self.data.setdefault("closed_trades", []).append(closed_trade)
                self._update_profile(wallet, closed_trade)

        self._save_data()
        return {
            "status": "recorded",
            "event": event,
            "closed_trade": closed_trade,
            "profile": self.data.get("profiles", {}).get(wallet),
        }

    def _compute_impact_score(
        self,
        amount_tao: float,
        total_stake_tao: float,
        market_cap_rank: Optional[int],
    ) -> float:
        """Estimate how much a wallet moves a small-cap subnet."""
        rank = market_cap_rank or 999
        max_rank = int(self.config.get("small_cap_max_market_cap_rank", 80))
        if rank > max_rank:
            return 0.0
        if total_stake_tao > 0:
            stake_ratio = min(1.0, amount_tao / total_stake_tao)
        else:
            stake_ratio = min(1.0, amount_tao / float(self.config.get("small_cap_stake_threshold_tao", 400000)))
        rank_factor = max(0.0, 1.0 - (rank / max_rank))
        return round(min(1.0, stake_ratio * 0.6 + rank_factor * 0.4), 3)

    def _update_profile(self, wallet: str, trade: Dict[str, Any]) -> None:
        profiles: Dict[str, Any] = self.data.setdefault("profiles", {})
        profile = profiles.setdefault(
            wallet,
            {
                "wallet": wallet,
                "first_seen": trade.get("entry_ts"),
                "last_seen": trade.get("exit_ts"),
                "closed_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_return_pct": None,
                "returns_pct": [],
                "hold_hours": [],
                "impact_scores": [],
                "early_moves": 0,
                "subnets": [],
                "subnet_timeline": [],
                "total_volume_tao": 0.0,
                "classifications": [],
                "scores": {},
                "tags": [],
            },
        )

        profile["closed_trades"] = int(profile.get("closed_trades", 0)) + 1
        profile["last_seen"] = trade.get("exit_ts")
        profile["total_volume_tao"] = round(
            float(profile.get("total_volume_tao", 0)) + float(trade.get("amount_tao", 0)), 2
        )

        hold = float(trade.get("hold_hours", 0))
        profile.setdefault("hold_hours", []).append(hold)
        profile["hold_hours"] = profile["hold_hours"][-100:]

        ret = trade.get("return_pct")
        if ret is not None:
            profile.setdefault("returns_pct", []).append(float(ret))
            profile["returns_pct"] = profile["returns_pct"][-100:]
            if ret > 0:
                profile["wins"] = int(profile.get("wins", 0)) + 1
            else:
                profile["losses"] = int(profile.get("losses", 0)) + 1

        impact = trade.get("impact_score", 0)
        if impact:
            profile.setdefault("impact_scores", []).append(float(impact))
            profile["impact_scores"] = profile["impact_scores"][-50:]

        pca = trade.get("price_change_after_entry")
        horizon = float(self.config.get("early_mover_horizon_hours", 24))
        min_move = float(self.config.get("early_mover_min_move_pct", 8.0))
        if hold <= horizon and pca is not None and abs(float(pca)) >= min_move:
            if (ret is not None and ret > 0) or (float(pca) > 0 and trade.get("entry_price")):
                profile["early_moves"] = int(profile.get("early_moves", 0)) + 1

        nuid = trade.get("netuid")
        subnets = profile.setdefault("subnets", [])
        if nuid is not None and nuid not in subnets:
            subnets.append(nuid)

        timeline = profile.setdefault("subnet_timeline", [])
        timeline.append({"netuid": nuid, "ts": trade.get("exit_ts"), "side": "sell"})
        profile["subnet_timeline"] = timeline[-200:]

        closed = profile["closed_trades"]
        wins = profile.get("wins", 0)
        profile["win_rate"] = round(wins / closed, 3) if closed else 0.0
        rets = profile.get("returns_pct", [])
        profile["avg_return_pct"] = round(statistics.mean(rets), 2) if rets else None
        profile["median_hold_hours"] = round(statistics.median(profile["hold_hours"]), 2) if profile["hold_hours"] else None
        profile["avg_impact_score"] = (
            round(statistics.mean(profile["impact_scores"]), 3) if profile.get("impact_scores") else 0.0
        )

        profile["scores"] = score_dimensions(profile, self.config)
        profile["classifications"] = classify_wallet(profile, self.config)
        profile["tags"] = profile["classifications"]
        profile["is_rugger"] = "ruggers" in profile["classifications"]
        profile["is_alpha_whale"] = "alpha_whales" in profile["classifications"]
        profile["is_market_mover"] = "market_movers" in profile["classifications"]
        profile["is_early_mover"] = "early_movers" in profile["classifications"]
        profile["is_conviction_holder"] = "conviction_holders" in profile["classifications"]
        profile["is_rotator"] = "rotators" in profile["classifications"]

    def get_leaderboard(self, category: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        limit = limit or int(self.config.get("leaderboard_limit", 50))
        if category not in TRACKING_DIMENSIONS:
            raise ValueError(f"Unknown category: {category}")

        profiles = [
            p for p in self.data.get("profiles", {}).values()
            if category in p.get("classifications", [])
        ]

        sort_keys = {
            "ruggers": lambda p: (p.get("scores", {}).get("rugger_risk", 0), p.get("closed_trades", 0)),
            "alpha_whales": lambda p: (p.get("win_rate", 0), p.get("avg_return_pct") or 0),
            "market_movers": lambda p: (p.get("avg_impact_score", 0), p.get("total_volume_tao", 0)),
            "early_movers": lambda p: (p.get("early_moves", 0), p.get("win_rate", 0)),
            "conviction_holders": lambda p: (p.get("median_hold_hours") or 0, p.get("win_rate", 0)),
            "rotators": lambda p: (len(p.get("subnets", [])), p.get("win_rate", 0)),
        }
        profiles.sort(key=sort_keys[category], reverse=True)
        return profiles[:limit]

    def get_all_leaderboards(self, limit: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
        return {cat: self.get_leaderboard(cat, limit) for cat in TRACKING_DIMENSIONS}

    def get_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        return self.data.get("profiles", {}).get(wallet.strip())

    def get_rugger_watchlist(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return self.get_leaderboard("ruggers", limit)

    def get_active_alerts(self) -> Dict[str, Any]:
        """Alerts: rugger exits imminent + alpha whale new entries."""
        now = datetime.now(timezone.utc)
        rugger_alerts = []
        follow_alerts = []
        open_positions = self.data.get("open_positions", {})
        profiles = self.data.get("profiles", {})

        for pos in open_positions.values():
            wallet = pos.get("wallet")
            profile = profiles.get(wallet) or {}
            classifications = profile.get("classifications", [])
            entry_ts = _parse_iso(pos.get("entry_ts"))
            hold_so_far = (now - entry_ts).total_seconds() / 3600.0 if entry_ts else 0.0

            base = {
                "wallet": wallet,
                "netuid": pos.get("netuid"),
                "subnet_name": pos.get("subnet_name"),
                "entry_ts": pos.get("entry_ts"),
                "amount_tao": pos.get("amount_tao"),
                "hold_hours_so_far": round(hold_so_far, 2),
            }

            if "ruggers" in classifications:
                median_hold = profile.get("median_hold_hours") or 24.0
                alert_before = float(self.config.get("alert_before_exit_hours", 2.0))
                estimated_exit_in = max(0.0, median_hold - hold_so_far)
                rugger_alerts.append({
                    **base,
                    "type": "rugger_exit_warning",
                    "median_hold_hours": median_hold,
                    "estimated_exit_in_hours": round(estimated_exit_in, 2),
                    "urgency": "high" if estimated_exit_in <= alert_before else "medium",
                    "recommendation": "do_not_follow",
                })
            elif "alpha_whales" in classifications or "early_movers" in classifications:
                follow_alerts.append({
                    **base,
                    "type": "smart_money_entry",
                    "classifications": classifications,
                    "win_rate": profile.get("win_rate"),
                    "avg_return_pct": profile.get("avg_return_pct"),
                    "recommendation": "consider_following",
                })

        rugger_alerts.sort(key=lambda a: a.get("estimated_exit_in_hours", 999))
        return {
            "rugger_alerts": rugger_alerts,
            "follow_alerts": follow_alerts,
            "total": len(rugger_alerts) + len(follow_alerts),
        }

    def _ledger_has_data(self) -> bool:
        return bool(self.data.get("events")) or bool(self.data.get("profiles"))

    def _ledger_honesty(self) -> Dict[str, Any]:
        has_data = self._ledger_has_data()
        return {
            "data_available": has_data,
            "source": "ledger",
            "reason": None if has_data else "no_events",
        }

    def get_subnet_flow(self, netuid: int) -> Dict[str, Any]:
        open_positions = self.data.get("open_positions", {})
        profiles = self.data.get("profiles", {})
        by_class: Dict[str, List[Dict[str, Any]]] = {c: [] for c in TRACKING_DIMENSIONS}

        for pos in open_positions.values():
            if int(pos.get("netuid", -1)) != int(netuid):
                continue
            wallet = pos.get("wallet")
            profile = profiles.get(wallet) or {}
            entry = {
                "wallet": wallet,
                "amount_tao": pos.get("amount_tao"),
                "entry_ts": pos.get("entry_ts"),
                "classifications": profile.get("classifications", []),
                "win_rate": profile.get("win_rate"),
            }
            for cls in profile.get("classifications", []):
                if cls in by_class:
                    by_class[cls].append(entry)

        flow: Dict[str, Any] = {
            "netuid": int(netuid),
            "open_positions": sum(len(v) for v in by_class.values()),
            "by_classification": by_class,
            **self._ledger_honesty(),
        }
        if flow["data_available"]:
            flow["avoid_follow"] = len(by_class.get("ruggers", [])) > 0
            flow["smart_money_present"] = bool(
                by_class.get("alpha_whales") or by_class.get("early_movers") or by_class.get("conviction_holders")
            )
        return flow

    def day_move_highlights(
        self,
        netuid: int,
        liquidity_tao: Optional[float] = None,
        hours: float = 24.0,
    ) -> Dict[str, Any]:
        """Biggest single whale tx in the window, plus largest by slippage proxy.

        No AMM slippage in the ledger — proxy is amount_tao / liquidity
        (caller liquidity, else event total_stake_tao). Honest-empty when no events.
        """
        honesty = self._ledger_honesty()
        empty: Dict[str, Any] = {
            "status": "success",
            **honesty,
            "netuid": int(netuid),
            "hours": hours,
            "biggest_tao": None,
            "biggest_slip": None,
            "same_event": False,
            "chips": [],
        }
        if not honesty["data_available"]:
            return empty

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=float(hours))
        min_notional = float(self.config.get("min_tao_notional", 50.0))
        try:
            liq_override = float(liquidity_tao) if liquidity_tao is not None else 0.0
        except (TypeError, ValueError):
            liq_override = 0.0

        best_tao: Optional[Dict[str, Any]] = None
        best_slip: Optional[Dict[str, Any]] = None
        best_tao_amt = -1.0
        best_slip_ratio = -1.0

        for ev in self.data.get("events") or []:
            if int(ev.get("netuid", -1)) != int(netuid):
                continue
            ts = _parse_iso(ev.get("timestamp"))
            if not ts or ts < cutoff:
                continue
            try:
                amt = float(ev.get("amount_tao") or 0)
            except (TypeError, ValueError):
                continue
            if amt < min_notional:
                continue
            side = (ev.get("side") or "").lower()
            if side not in ("buy", "sell"):
                continue

            try:
                ev_stake = float(ev.get("total_stake_tao") or 0)
            except (TypeError, ValueError):
                ev_stake = 0.0
            # Rank by event-time float when known (thin-name hits win); else live liquidity.
            rank_liq = ev_stake if ev_stake > 0 else liq_override
            # Display % of float prefers live liquidity when the caller supplied it.
            disp_liq = liq_override if liq_override > 0 else ev_stake
            slip_ratio = (amt / rank_liq) if rank_liq > 0 else None
            slip_pct = (
                round((amt / disp_liq) * 100.0, 2) if disp_liq > 0 else None
            )

            row = {
                "wallet": ev.get("wallet"),
                "wallet_short": _short_ss58(str(ev.get("wallet") or "")),
                "side": side,
                "amount_tao": round(amt, 4),
                "timestamp": ev.get("timestamp"),
                "tx_hash": ev.get("tx_hash"),
                "slip_pct": slip_pct,
            }
            if amt > best_tao_amt:
                best_tao_amt = amt
                best_tao = row
            if slip_ratio is not None and slip_ratio > best_slip_ratio:
                best_slip_ratio = slip_ratio
                best_slip = row

        same = bool(
            best_tao
            and best_slip
            and best_tao.get("wallet") == best_slip.get("wallet")
            and best_tao.get("timestamp") == best_slip.get("timestamp")
            and best_tao.get("amount_tao") == best_slip.get("amount_tao")
            and best_tao.get("side") == best_slip.get("side")
        )
        chips: List[str] = []
        if best_tao and same:
            chips.append(_day_whale_chip(best_tao, include_slip=True))
        else:
            if best_tao:
                chips.append(_day_whale_chip(best_tao, include_slip=False))
            if best_slip:
                chips.append(_slip_day_chip(best_slip))

        return {
            "status": "success",
            "data_available": True,
            "source": "ledger",
            "reason": None,
            "netuid": int(netuid),
            "hours": hours,
            "biggest_tao": best_tao,
            "biggest_slip": best_slip,
            "same_event": same,
            "chips": chips,
        }

    def detect_flow_signals(self, hours: int = 24) -> Dict[str, Any]:
        """Per-subnet flow flips and volume surges from the event ledger."""
        honesty = self._ledger_honesty()
        if not honesty["data_available"]:
            return {
                "status": "success",
                **honesty,
                "hours": hours,
                "signals": [],
                "summary": {
                    "accumulation": 0,
                    "distribution": 0,
                    "flips": 0,
                    "surges": 0,
                    "total_net_flow_tao": 0.0,
                },
            }

        now = datetime.now(timezone.utc)
        cur_start = now - timedelta(hours=hours)
        prev_start = now - timedelta(hours=hours * 2)
        min_notional = float(self.config.get("min_tao_notional", 50.0))

        # ponytail: O(events) scan — fine for ledger scale; upgrade path: pre-aggregate windows
        cur: Dict[int, Dict[str, float]] = {}
        prev: Dict[int, Dict[str, float]] = {}
        names: Dict[int, str] = {}

        for ev in self.data.get("events") or []:
            ts = _parse_iso(ev.get("timestamp"))
            if not ts:
                continue
            nuid = ev.get("netuid")
            if nuid is None:
                continue
            nuid = int(nuid)
            amt = float(ev.get("amount_tao") or 0)
            if amt < min_notional:
                continue
            side = (ev.get("side") or "").lower()
            signed = amt if side == "buy" else -amt if side == "sell" else 0.0
            if not signed:
                continue
            if ev.get("subnet_name"):
                names[nuid] = str(ev["subnet_name"])

            if ts >= cur_start:
                bucket = cur.setdefault(nuid, {"net": 0.0, "vol": 0.0, "buys": 0, "sells": 0})
                bucket["net"] += signed
                bucket["vol"] += amt
                if side == "buy":
                    bucket["buys"] += 1
                else:
                    bucket["sells"] += 1
            elif ts >= prev_start:
                bucket = prev.setdefault(nuid, {"net": 0.0, "vol": 0.0, "buys": 0, "sells": 0})
                bucket["net"] += signed
                bucket["vol"] += amt

        all_netuids = set(cur) | set(prev)
        signals: List[Dict[str, Any]] = []
        acc_count = dist_count = flip_count = surge_count = 0
        total_net = 0.0

        for nuid in all_netuids:
            c = cur.get(nuid, {"net": 0.0, "vol": 0.0, "buys": 0, "sells": 0})
            p = prev.get(nuid, {"net": 0.0, "vol": 0.0})
            net = round(c["net"], 4)
            total_net += net
            prev_net = round(p["net"], 4)
            vol = round(c["vol"], 4)
            prev_vol = round(p["vol"], 4)

            flip_dir = None
            if prev_net < 0 <= net or prev_net <= 0 < net:
                flip_dir = "accumulation"
                flip_count += 1
            elif prev_net > 0 >= net or prev_net >= 0 > net:
                flip_dir = "distribution"
                flip_count += 1

            surge = prev_vol > 0 and vol >= prev_vol * 2 and vol >= min_notional * 2
            if surge:
                surge_count += 1

            if net > 0:
                acc_count += 1
            elif net < 0:
                dist_count += 1

            if flip_dir is None and not surge and abs(net) < min_notional:
                continue

            flow = self.get_subnet_flow(nuid)
            strength = min(100, int(abs(net) / max(min_notional, 1) * 10 + (20 if flip_dir else 0) + (15 if surge else 0)))

            sig: Dict[str, Any] = {
                "netuid": nuid,
                "subnet_name": names.get(nuid),
                "net_flow_tao": net,
                "prev_net_flow_tao": prev_net,
                "volume_tao": vol,
                "buy_wallets": c.get("buys", 0),
                "sell_wallets": c.get("sells", 0),
                "strength": strength,
                "rugger_count": len(flow.get("by_classification", {}).get("ruggers", [])),
                "avoid_follow": flow.get("avoid_follow", False),
            }
            if flip_dir:
                sig["kind"] = "flow_flip"
                sig["flip_direction"] = flip_dir
                sig["label"] = (
                    f"24h flow flipped green · +{net}τ"
                    if flip_dir == "accumulation"
                    else f"24h flow flipped red · {net}τ"
                )
            elif surge:
                sig["kind"] = "volume_surge"
                sig["label"] = f"Volume surge · {vol}τ"
            else:
                sig["kind"] = "net_flow"
                sig["label"] = f"Net {'buying' if net > 0 else 'selling'} · {net:+}τ"

            signals.append(sig)

        signals.sort(key=lambda s: s.get("strength", 0), reverse=True)
        return {
            "status": "success",
            "data_available": True,
            "source": "ledger",
            "hours": hours,
            "signals": signals,
            "summary": {
                "accumulation": acc_count,
                "distribution": dist_count,
                "flips": flip_count,
                "surges": surge_count,
                "total_net_flow_tao": round(total_net, 4),
            },
        }

    def discount_score(self, netuid: int, base_score: float) -> Tuple[float, Dict[str, Any]]:
        flow = self.get_subnet_flow(netuid)
        ruggers = flow.get("by_classification", {}).get("ruggers", [])
        if not ruggers:
            return base_score, {"adjusted": False, "reason": "no_rugger_exposure"}

        profiles = self.data.get("profiles", {})
        max_risk = max(
            (profiles.get(r["wallet"], {}).get("scores", {}).get("rugger_risk", 0.5) for r in ruggers),
            default=0.5,
        )
        penalty = min(0.35, 0.15 + max_risk * 0.25)
        adjusted = round(max(0.0, base_score * (1.0 - penalty)), 4)
        return adjusted, {
            "adjusted": True,
            "penalty": round(penalty, 3),
            "rugger_count": len(ruggers),
            "max_risk_score": max_risk,
        }

    def summary(self) -> Dict[str, Any]:
        profiles = self.data.get("profiles", {})
        counts = {cat: len(self.get_leaderboard(cat, limit=9999)) for cat in TRACKING_DIMENSIONS}
        return {
            "status": "success",
            "service": "whale_intelligence",
            "updated_at": self.data.get("updated_at"),
            "dimensions": TRACKING_DIMENSIONS,
            "config": self.config,
            **self._ledger_honesty(),
            "stats": {
                "total_wallets_tracked": len(profiles),
                "open_positions": len(self.data.get("open_positions", {})),
                "closed_trades": len(self.data.get("closed_trades", [])),
                "total_events": len(self.data.get("events", [])),
                "by_classification": counts,
            },
        }
