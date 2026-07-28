"""Echo Kin — pulse lookalikes that haven't moved yet (SimiVision, not DNA clones).

Inspired by competitor “who looks like the mover” framing, but our own terms:

- **Pulse** — triad + flow vector from the pump ladder (what rhymes on-chain)
- **Echo Kin** — same pulse shape, quieter / earlier phase (opportunity angle)
- **Lane tag** — Coil · Quiet Load · Pressure · Lift · Drift · Hollow
- **Signature rarity** — how uncommon this pulse is on the live ladder (0–100)

No new scoring engine — L1 / Hamming on existing ladder signal_snapshot + triad.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_PHASE_RANK = {
    "DORMANT": 0,
    "STIRRING": 1,
    "ACCUMULATING": 2,
    "PUMPING": 3,
    "COOLING": 4,
    "EXITING": 5,
}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _snapshot(entry: Dict[str, Any]) -> Dict[str, Any]:
    raw = entry.get("signal_snapshot")
    return dict(raw) if isinstance(raw, dict) else {}


def _triad_bits(entry: Dict[str, Any]) -> Tuple[int, int, int]:
    snap = _snapshot(entry)
    try:
        from internal.pump.triad import compute_pump_triad

        triad = compute_pump_triad(snap)
    except Exception:
        triad = {}
    return (
        1 if triad.get("inflow_quiet_load") else 0,
        1 if triad.get("buy_pressure") else 0,
        1 if triad.get("price_coil") else 0,
    )


def pulse_vector(entry: Dict[str, Any]) -> Tuple[float, ...]:
    """Normalized pulse: triad bits + buy / vol / 1h momentum."""
    snap = _snapshot(entry)
    bits = _triad_bits(entry)
    buy = max(0.0, min(1.0, _f(snap.get("buy_ratio"), 0.5)))
    vol = max(0.0, min(1.0, _f(snap.get("volume_intensity"))))
    mom = max(-1.0, min(1.0, _f(snap.get("momentum_1h"))))
    # Map mom into 0..1 around flat for distance math.
    mom_u = (mom + 0.05) / 0.10
    mom_u = max(0.0, min(1.0, mom_u))
    return (float(bits[0]), float(bits[1]), float(bits[2]), buy, vol, mom_u)


def pulse_distance(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    """Weighted L1 — triad bits count more than soft flow floats."""
    if len(a) != len(b):
        return 99.0
    weights = (1.2, 1.2, 1.2, 0.8, 0.8, 0.5)
    return sum(w * abs(x - y) for w, x, y in zip(weights, a, b))


def lane_tag(entry: Dict[str, Any]) -> str:
    """Our lane vocabulary — not competitor archetype names."""
    phase = str(entry.get("phase") or "DORMANT").upper()
    bits = _triad_bits(entry)
    inflow, pressure, coil = bits
    score = _f(entry.get("composite_score"))
    if phase in ("COOLING", "EXITING"):
        return "Drift"
    if phase == "PUMPING" or score >= 0.78:
        return "Lift"
    if coil and not pressure:
        return "Coil"
    if inflow and not coil:
        return "Quiet Load"
    if pressure:
        return "Pressure"
    if phase in ("DORMANT",) or score < 0.25:
        return "Hollow"
    return "Quiet Load" if inflow else "Coil"


def _shared_pulse(a: Tuple[float, ...], b: Tuple[float, ...]) -> List[str]:
    labels = []
    names = ("quiet load", "buy pressure", "coil")
    for i, name in enumerate(names):
        if a[i] >= 0.5 and b[i] >= 0.5:
            labels.append(name)
    if abs(a[3] - b[3]) < 0.08 and a[3] >= 0.52:
        labels.append("buy flow")
    if abs(a[4] - b[4]) < 0.12 and a[4] >= 0.15:
        labels.append("vol heat")
    return labels


def signature_rarity(focus: Tuple[float, ...], universe: List[Tuple[float, ...]]) -> int:
    """0–100 — higher = fewer ladder peers with similar triad (rarer pulse)."""
    if not universe:
        return 50
    similar = 0
    for vec in universe:
        # Hamming on triad bits only
        ham = sum(1 for i in range(3) if (focus[i] >= 0.5) != (vec[i] >= 0.5))
        if ham <= 1:
            similar += 1
    # Exclude self-ish: similar always includes focus when in universe
    ratio = similar / max(1, len(universe))
    rarity = int(round((1.0 - min(1.0, ratio)) * 100))
    return max(0, min(100, rarity))


def _quieter_than(focus: Dict[str, Any], other: Dict[str, Any]) -> bool:
    """Kin should still be earlier / quieter than the focus mover."""
    fp = _PHASE_RANK.get(str(focus.get("phase") or "").upper(), 0)
    op = _PHASE_RANK.get(str(other.get("phase") or "").upper(), 0)
    if op < fp:
        return True
    if op > fp:
        return False
    return _f(other.get("composite_score")) < _f(focus.get("composite_score")) - 0.04


def _entry_name(entry: Dict[str, Any]) -> str:
    raw = entry.get("name") or entry.get("subnet_name")
    if raw and str(raw).strip():
        return str(raw).strip()
    try:
        return f"SN{int(entry.get('netuid'))}"
    except (TypeError, ValueError):
        return "subnet"


def find_echo_kin(
    focus_netuid: int,
    state: Dict[str, Any],
    *,
    limit: int = 3,
    max_distance: float = 1.85,
) -> Dict[str, Any]:
    """Return Echo Kin payload for a focus netuid from pump ladder state."""
    subnets = state.get("subnets") or {}
    if not isinstance(subnets, dict):
        return {"lane": None, "rarity": None, "kin": [], "why": None}

    focus: Optional[Dict[str, Any]] = None
    for entry in subnets.values():
        if not isinstance(entry, dict):
            continue
        try:
            if int(entry.get("netuid")) == int(focus_netuid):
                focus = entry
                break
        except (TypeError, ValueError):
            continue
    if focus is None:
        return {"lane": None, "rarity": None, "kin": [], "why": None}

    focus_vec = pulse_vector(focus)
    universe: List[Tuple[float, ...]] = []
    candidates: List[Tuple[float, Dict[str, Any]]] = []
    for entry in subnets.values():
        if not isinstance(entry, dict):
            continue
        try:
            nid = int(entry.get("netuid"))
        except (TypeError, ValueError):
            continue
        vec = pulse_vector(entry)
        universe.append(vec)
        if nid == int(focus_netuid):
            continue
        if nid <= 0:
            continue
        if not _snapshot(entry):
            continue
        if not _quieter_than(focus, entry):
            continue
        dist = pulse_distance(focus_vec, vec)
        if dist <= max_distance:
            candidates.append((dist, entry))

    candidates.sort(key=lambda row: (row[0], -_f(row[1].get("composite_score"))))
    kin: List[Dict[str, Any]] = []
    for dist, entry in candidates[: max(0, limit)]:
        try:
            nid = int(entry.get("netuid"))
        except (TypeError, ValueError):
            continue
        shared = _shared_pulse(focus_vec, pulse_vector(entry))
        kin.append(
            {
                "netuid": nid,
                "name": _entry_name(entry),
                "lane": lane_tag(entry),
                "phase": str(entry.get("phase") or "").upper(),
                "distance": round(dist, 3),
                "shared": shared,
                "score": round(_f(entry.get("composite_score")), 2),
            }
        )

    lane = lane_tag(focus)
    rarity = signature_rarity(focus_vec, universe)
    if kin:
        top = kin[0]
        shared_txt = ", ".join(top["shared"][:3]) if top["shared"] else "similar pulse"
        why = (
            f"Echo Kin: SN{top['netuid']} still quieter with {shared_txt} — "
            f"same lane shape, less move."
        )
    else:
        why = f"Lane {lane} · signature rarity {rarity} — no quieter kin on the ladder yet."

    return {
        "lane": lane,
        "rarity": rarity,
        "kin": kin,
        "why": why,
    }


def attach_echo_to_desk(
    payload: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach echo block to hero (+ desk-level echo summary). Mutates payload."""
    hero = payload.get("hero")
    if not isinstance(hero, dict) or hero.get("netuid") is None:
        return payload
    try:
        netuid = int(hero["netuid"])
    except (TypeError, ValueError):
        return payload
    echo = find_echo_kin(netuid, state)
    hero["echo"] = echo
    hero["lane"] = echo.get("lane")
    hero["signature_rarity"] = echo.get("rarity")
    payload["echo"] = {
        "focus_netuid": netuid,
        "lane": echo.get("lane"),
        "rarity": echo.get("rarity"),
        "kin_count": len(echo.get("kin") or []),
        "why": echo.get("why"),
    }
    return payload
