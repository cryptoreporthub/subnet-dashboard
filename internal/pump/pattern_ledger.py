"""Intraday pump waveform segment ledger (PP-0).

Records directional legs (up / down / flat) per subnet on each ladder scan so
pattern classifiers can spot shapes like pump → drop → re-pump.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.file_utils import safe_read_json, safe_write_json

logger = logging.getLogger(__name__)

_lock = threading.RLock()

STATE_PATH = os.environ.get("PUMP_PATTERN_LEDGER_PATH", "data/pump_pattern_ledger.json")
MAX_SEGMENTS = 48
FLAT_THRESHOLD_PCT = float(os.environ.get("PUMP_PATTERN_FLAT_PCT", "0.3"))


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _minutes_between(start: Optional[str], end: datetime) -> float:
    start_dt = _parse_ts(start)
    if start_dt is None:
        return 0.0
    return max(0.0, (end - start_dt).total_seconds() / 60.0)


def _default_state() -> Dict[str, Any]:
    return {"version": "1.0", "subnets": {}, "meta": {"updated_at": _now_z()}}


def load_ledger(path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or STATE_PATH
    with _lock:
        data = safe_read_json(resolved, default=_default_state())
        if not isinstance(data, dict):
            return _default_state()
        data.setdefault("subnets", {})
        data.setdefault("meta", {})
        return data


def save_ledger(data: Dict[str, Any], path: Optional[str] = None) -> None:
    resolved = path or STATE_PATH
    data.setdefault("meta", {})["updated_at"] = _now_z()
    with _lock:
        safe_write_json(resolved, data)


def _direction(ret_pct: float) -> str:
    if abs(ret_pct) < FLAT_THRESHOLD_PCT:
        return "flat"
    return "up" if ret_pct > 0 else "down"


def _close_open_segment(entry: Dict[str, Any], *, end: str, end_price: float) -> None:
    open_seg = entry.get("open_segment")
    if not isinstance(open_seg, dict):
        return
    start_price = float(open_seg.get("start_price") or 0)
    magnitude = 0.0
    if start_price > 0:
        magnitude = round((end_price - start_price) / start_price * 100.0, 4)
    closed = dict(open_seg)
    closed["end"] = end
    closed["duration_min"] = round(
        _minutes_between(closed.get("start"), _parse_ts(end) or datetime.now(timezone.utc)),
        2,
    )
    closed["magnitude_pct"] = magnitude
    segments = entry.setdefault("segments", [])
    segments.append(closed)
    entry["segments"] = segments[-MAX_SEGMENTS:]
    entry["open_segment"] = None


def _open_segment(
    entry: Dict[str, Any],
    *,
    direction: str,
    start: str,
    start_price: float,
    phase: str,
) -> None:
    entry["open_segment"] = {
        "direction": direction,
        "start": start,
        "start_price": start_price,
        "phase_overlay": phase,
    }


def append_ladder_sample(
    netuid: Any,
    *,
    price: float,
    phase: str,
    name: Optional[str] = None,
    now: Optional[datetime] = None,
    path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Record one price sample from the pump ladder scan."""
    try:
        nu = int(netuid)
    except (TypeError, ValueError):
        return None
    if nu < 1:
        return None
    try:
        px = float(price)
    except (TypeError, ValueError):
        return None
    if px <= 0:
        return None

    now = now or datetime.now(timezone.utc)
    ts = now.isoformat().replace("+00:00", "Z")
    phase = str(phase or "DORMANT").upper()

    data = load_ledger(path)
    key = str(nu)
    subnets = data.setdefault("subnets", {})
    entry = subnets.get(key) or {
        "netuid": nu,
        "name": name,
        "segments": [],
        "open_segment": None,
        "last_price": None,
    }
    if name:
        entry["name"] = name

    last_price = entry.get("last_price")
    if last_price is None:
        entry["last_price"] = px
        _open_segment(entry, direction="flat", start=ts, start_price=px, phase=phase)
        subnets[key] = entry
        save_ledger(data, path)
        return entry

    try:
        prev = float(last_price)
    except (TypeError, ValueError):
        prev = px
    ret_pct = ((px - prev) / prev * 100.0) if prev > 0 else 0.0
    direction = _direction(ret_pct)

    if phase == "COOLING":
        _close_open_segment(entry, end=ts, end_price=px)
    else:
        open_seg = entry.get("open_segment")
        if not isinstance(open_seg, dict):
            _open_segment(entry, direction=direction, start=ts, start_price=px, phase=phase)
        elif open_seg.get("direction") != direction:
            _close_open_segment(entry, end=ts, end_price=px)
            _open_segment(entry, direction=direction, start=ts, start_price=px, phase=phase)
        else:
            open_seg["phase_overlay"] = phase

    entry["last_price"] = px
    entry["last_sample_at"] = ts
    subnets[key] = entry
    save_ledger(data, path)

    if os.environ.get("PUMP_SEGMENT_TRAIL", "").strip().lower() in ("1", "true", "yes", "on"):
        _maybe_emit_segment_close(entry, nu, name)

    return entry


def _maybe_emit_segment_close(entry: Dict[str, Any], netuid: int, name: Optional[str]) -> None:
    segments = entry.get("segments") or []
    if not segments:
        return
    last = segments[-1]
    try:
        from internal.learning.trail_events import emit_trail_event

        emit_trail_event(
            "pump_segment_close",
            subnet=name or f"SN{netuid}",
            netuid=netuid,
            evidence={
                "direction": last.get("direction"),
                "duration_min": last.get("duration_min"),
                "magnitude_pct": last.get("magnitude_pct"),
            },
            signal=f"pump_segment_{last.get('direction', 'flat')}",
            decision="segment_close",
        )
    except Exception as exc:
        logger.debug("pump segment trail skipped SN%s: %s", netuid, exc)


# Leg separator — not → (that arrow is reserved for flat / stable price only).
_STRIP_LEG_SEP = " · "


def _segment_arrow(direction: str) -> str:
    if direction == "up":
        return "↑"
    if direction == "down":
        return "↓"
    return "→"


def _format_magnitude_pct(mag: Any) -> str:
    try:
        val = float(mag)
    except (TypeError, ValueError):
        return "—"
    if abs(val) < 1e-9:
        return "—"
    if val > 0:
        return f"+{val:.1f}%"
    return f"{val:.1f}%"


def _format_segment_leg(seg: Dict[str, Any], *, live: bool = False) -> str:
    direction = str(seg.get("direction") or "flat")
    arrow = _segment_arrow(direction)
    pct_txt = _format_magnitude_pct(seg.get("magnitude_pct"))
    dur = float(seg.get("duration_min") or 0)
    suffix = "*" if live else ""
    return f"{arrow}{pct_txt}({_bucket_duration(dur)}){suffix}"


def format_direction_strip(
    segments: List[Dict[str, Any]],
    *,
    max_legs: int = 5,
    live_last: bool = False,
) -> str:
    """Directional path: ``↑+4.0%(2h) · ↓-2.0%(1h) · →—(30m) · ↑+2.5%(45m)*``."""
    if not segments:
        return ""
    legs: List[str] = []
    window = segments[-max_legs:]
    for idx, seg in enumerate(window):
        if not isinstance(seg, dict):
            continue
        live = live_last and idx == len(window) - 1
        legs.append(_format_segment_leg(seg, live=live))
    return _STRIP_LEG_SEP.join(legs)


def _bucket_duration(minutes: float) -> str:
    if minutes < 45:
        return f"{int(round(minutes))}m"
    hours = minutes / 60.0
    if hours < 2:
        return f"{hours:.1f}h".replace(".0h", "h")
    return f"{int(round(hours))}h"


def _waveform_label(entry: Dict[str, Any]) -> str:
    parts: List[str] = []
    for seg in (entry.get("segments") or [])[-5:]:
        if not isinstance(seg, dict):
            continue
        direction = seg.get("direction")
        if direction == "up":
            arrow = "↑"
        elif direction == "down":
            arrow = "↓"
        else:
            arrow = "→"
        dur = float(seg.get("duration_min") or 0)
        parts.append(f"{arrow}{_bucket_duration(dur)}")
    open_seg = entry.get("open_segment")
    if isinstance(open_seg, dict):
        direction = open_seg.get("direction")
        arrow = "↑" if direction == "up" else "↓" if direction == "down" else "→"
        dur = _minutes_between(open_seg.get("start"), datetime.now(timezone.utc))
        parts.append(f"{arrow}{_bucket_duration(dur)}*")
    return _STRIP_LEG_SEP.join(parts) if parts else ""


def _segment_directions(segments: List[Dict[str, Any]], *, max_legs: int = 5) -> List[str]:
    dirs: List[str] = []
    for seg in segments[-max_legs:]:
        if not isinstance(seg, dict):
            continue
        direction = str(seg.get("direction") or "flat")
        if direction == "flat" and dirs and dirs[-1] == "flat":
            continue
        dirs.append(direction)
    return [d for d in dirs if d != "flat"] or [d for d in dirs]


def _shape_hash(directions: List[str]) -> str:
    return "-".join(directions) if directions else ""


def classify_waveform(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify recent segment directions into v1 pump pattern taxonomy."""
    legs = _segment_directions(segments)
    if len(legs) < 2:
        return {
            "pattern_class": "insufficient_data",
            "pattern_label": "",
            "confidence": 0.0,
            "shape_hash": _shape_hash(legs),
        }

    seq = tuple(legs[-5:])
    net_up = sum(float(s.get("magnitude_pct") or 0) for s in segments if s.get("direction") == "up")
    net_mag = sum(float(s.get("magnitude_pct") or 0) for s in segments[-5:])

    pattern_class = "CHOP"
    confidence = 0.55
    if seq == ("up",):
        pattern_class, confidence = "PUMP_ONLY", 0.9
    elif seq[:2] == ("up", "down") and len(seq) == 2:
        pattern_class, confidence = "PUMP_DROP", 0.85
    elif seq[:3] == ("up", "down", "up"):
        pattern_class, confidence = "PUMP_DROP_RE_PUMP", 0.88
    elif seq[:2] == ("down", "up"):
        pattern_class, confidence = "DROP_RELIEF", 0.8
    elif legs.count("up") >= 3 and net_up > 3.0:
        pattern_class, confidence = "GRIND_UP", 0.75
    elif len(legs) >= 4 and abs(net_mag) < 1.0:
        pattern_class, confidence = "CHOP", 0.7
    elif "flat" in [s.get("direction") for s in segments[-3:]] and legs[-1] == "up":
        pattern_class, confidence = "FLAT_COIL", 0.72

    label_parts = []
    for seg in segments[-5:]:
        if not isinstance(seg, dict):
            continue
        direction = seg.get("direction")
        arrow = "↑" if direction == "up" else "↓" if direction == "down" else "→"
        dur = float(seg.get("duration_min") or 0)
        label_parts.append(f"{arrow}{_bucket_duration(dur)}")
    pattern_label = _STRIP_LEG_SEP.join(label_parts)

    return {
        "pattern_class": pattern_class,
        "pattern_label": pattern_label,
        "confidence": round(confidence, 3),
        "shape_hash": _shape_hash(list(seq)),
    }


def typical_pattern_class(netuid: Any, path: Optional[str] = None) -> str:
    """Rolling typical class — ponytail: current classifier output until history accrues."""
    payload = pattern_payload(netuid, path=path)
    return str(payload.get("pattern_class") or "insufficient_data")


def _re_pump_from_match(match: Dict[str, Any]) -> float:
    cls = match.get("pattern_class")
    conf = float(match.get("confidence") or 0)
    if cls == "PUMP_DROP_RE_PUMP":
        return round(min(0.85, 0.55 + conf * 0.3), 4)
    if cls in {"FLAT_COIL", "GRIND_UP"}:
        return round(min(0.6, 0.35 + conf * 0.25), 4)
    return 0.0


def re_pump_prob_from_pattern(netuid: Any, path: Optional[str] = None) -> float:
    """Pattern-aware re-pump hint for ladder surfaces (PP-1)."""
    data = load_ledger(path)
    entry = (data.get("subnets") or {}).get(str(int(netuid))) or {}
    segments = list(entry.get("segments") or [])
    return _re_pump_from_match(classify_waveform(segments))


def pattern_payload(netuid: Any, path: Optional[str] = None) -> Dict[str, Any]:
    try:
        nu = int(netuid)
    except (TypeError, ValueError):
        return {"netuid": netuid, "segments": [], "waveform": ""}
    data = load_ledger(path)
    entry = (data.get("subnets") or {}).get(str(nu)) or {}
    segments = list(entry.get("segments") or [])
    open_seg = entry.get("open_segment")
    live_last = False
    if isinstance(open_seg, dict):
        now = datetime.now(timezone.utc)
        live = dict(open_seg)
        live["end"] = now.isoformat().replace("+00:00", "Z")
        live["duration_min"] = round(_minutes_between(live.get("start"), now), 2)
        start_price = float(live.get("start_price") or entry.get("last_price") or 0)
        last_price = float(entry.get("last_price") or start_price)
        if start_price > 0:
            live["magnitude_pct"] = round((last_price - start_price) / start_price * 100.0, 4)
        segments = segments + [live]
        live_last = True
    match = classify_waveform(segments)
    direction_strip = (
        format_direction_strip(segments, live_last=live_last) if segments else ""
    )
    display_label = direction_strip or match["pattern_label"] or _waveform_label(entry)
    return {
        "netuid": nu,
        "name": entry.get("name"),
        "segments": segments,
        "waveform": _waveform_label(entry),
        "segment_count": len(entry.get("segments") or []),
        "pattern_class": match["pattern_class"],
        "direction_strip": direction_strip,
        "pattern_label": display_label,
        "confidence": match["confidence"],
        "shape_hash": match["shape_hash"],
        "typical_pattern": match["pattern_class"],
        "re_pump_prob": _re_pump_from_match(match),
    }


def active_patterns(limit: int = 12, path: Optional[str] = None) -> List[Dict[str, Any]]:
    data = load_ledger(path)
    items: List[Dict[str, Any]] = []
    for entry in (data.get("subnets") or {}).values():
        if not isinstance(entry, dict):
            continue
        if not entry.get("segments") and not entry.get("open_segment"):
            continue
        nu = entry.get("netuid")
        payload = pattern_payload(nu, path=path)
        payload["last_sample_at"] = entry.get("last_sample_at")
        items.append(payload)
    items.sort(key=lambda row: row.get("last_sample_at") or "", reverse=True)
    return items[: max(1, limit)]
