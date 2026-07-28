"""Combined next-up + peer rank — experimental, transparent components.

UI keeps **Next up** and **Peers** as separate lines. The combined equation
ranks a full slate (tracked) and surfaces one pick labeled experimental.

Weights (ponytail defaults — tune after n>= graded):
  combined = 0.70 * timing + 0.30 * peer
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from internal.pump.peers import (
    _entry_name,
    _f,
    _quieter_than,
    _snapshot,
    find_peers,
    lane_tag,
    pulse_distance,
    pulse_vector,
)

W_TIMING = 0.70
W_PEER = 0.30
MAX_PEER_DISTANCE = 1.85
TRACK_LIMIT = 5
NEXT_UP_UI = 3
COMBINED_UI = 1

_PHASE_EARLY = frozenset({"DORMANT", "STIRRING", "ACCUMULATING"})
_PHASE_LATE = frozenset({"COOLING", "EXITING"})


def _trigger() -> float:
    try:
        from internal.learning.pump_calibration import effective_lead_gates

        return float(effective_lead_gates().get("just_started_max_score", 0.72))
    except Exception:
        return 0.72


def timing_points(entry: Dict[str, Any], *, trigger: Optional[float] = None) -> float:
    """0–100 — closer to pump gate from below scores higher."""
    trig = float(trigger if trigger is not None else _trigger())
    trig = max(trig, 1e-6)
    score = _f(entry.get("composite_score"))
    phase = str(entry.get("phase") or "").upper()
    # Progress toward trigger (cap at 1.0). Past-trigger still ranks but soft-penalize chase.
    progress = min(1.15, score / trig)
    pts = min(100.0, progress * 100.0)
    if phase in _PHASE_LATE:
        pts *= 0.35
    elif phase == "PUMPING" and score >= trig:
        pts *= 0.55  # already moving — not "next up"
    elif phase in _PHASE_EARLY:
        pts *= 1.0
    return round(max(0.0, min(100.0, pts)), 1)


def peer_points(
    focus_vec: Tuple[float, ...],
    entry: Dict[str, Any],
    *,
    max_distance: float = MAX_PEER_DISTANCE,
) -> float:
    """0–100 — pulse proximity to hero (0 if beyond distance gate)."""
    vec = pulse_vector(entry)
    dist = pulse_distance(focus_vec, vec)
    if dist > max_distance:
        return 0.0
    return round(max(0.0, min(100.0, (1.0 - dist / max_distance) * 100.0)), 1)


def combined_points(timing: float, peer: float) -> float:
    return round(W_TIMING * timing + W_PEER * peer, 1)


def _price(entry: Dict[str, Any]) -> float:
    snap = _snapshot(entry)
    for key in ("price", "tao_price", "price_tao"):
        p = _f(snap.get(key) or entry.get(key), 0.0)
        if p > 0:
            return p
    return 0.0


def _row(
    entry: Dict[str, Any],
    *,
    timing: float,
    peer: float,
    combined: float,
) -> Dict[str, Any]:
    try:
        nid = int(entry.get("netuid"))
    except (TypeError, ValueError):
        nid = 0
    return {
        "netuid": nid,
        "name": _entry_name(entry),
        "lane": lane_tag(entry),
        "phase": str(entry.get("phase") or "").upper(),
        "score": round(_f(entry.get("composite_score")), 2),
        "timing_pts": timing,
        "peer_pts": peer,
        "combined_pts": combined,
        "price": _price(entry),
    }


def rank_desk_angles(
    focus_netuid: int,
    state: Dict[str, Any],
    *,
    track_limit: int = TRACK_LIMIT,
) -> Dict[str, Any]:
    """Compute Next up, Peers, and Combined (experimental) from ladder state."""
    empty = {
        "experimental": True,
        "weights": {"timing": W_TIMING, "peer": W_PEER},
        "next_up": [],
        "peers": {"lane": None, "rarity": None, "matches": [], "why": None},
        "combined": None,
        "tracked": [],
        "why": None,
    }
    subnets = state.get("subnets") or {}
    if not isinstance(subnets, dict):
        return empty

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
        return empty

    focus_vec = pulse_vector(focus)
    trig = _trigger()
    peers_payload = find_peers(int(focus_netuid), state)

    timing_rows: List[Tuple[float, Dict[str, Any]]] = []
    combined_rows: List[Tuple[float, Dict[str, Any], float, float]] = []

    for entry in subnets.values():
        if not isinstance(entry, dict):
            continue
        try:
            nid = int(entry.get("netuid"))
        except (TypeError, ValueError):
            continue
        if nid <= 0 or nid == int(focus_netuid):
            continue
        if not _snapshot(entry):
            continue
        t_pts = timing_points(entry, trigger=trig)
        p_pts = peer_points(focus_vec, entry)
        # Next-up pool: early / near-gate names (not cooling)
        phase = str(entry.get("phase") or "").upper()
        if phase not in _PHASE_LATE and t_pts >= 25.0:
            timing_rows.append((t_pts, entry))
        # Combined pool: needs some timing OR peer signal
        if t_pts < 15.0 and p_pts < 20.0:
            continue
        # Prefer quieter-than-focus when peer weight matters; still allow hot timing alone
        if p_pts >= 20.0 and not _quieter_than(focus, entry) and t_pts < 55.0:
            continue
        c_pts = combined_points(t_pts, p_pts)
        combined_rows.append((c_pts, entry, t_pts, p_pts))

    timing_rows.sort(key=lambda r: (-r[0], -_f(r[1].get("composite_score"))))
    combined_rows.sort(key=lambda r: (-r[0], -r[2], -r[3]))

    next_up = [
        _row(entry, timing=t, peer=peer_points(focus_vec, entry), combined=combined_points(t, peer_points(focus_vec, entry)))
        for t, entry in timing_rows[:NEXT_UP_UI]
    ]

    tracked = [
        _row(entry, timing=t_pts, peer=p_pts, combined=c_pts)
        for c_pts, entry, t_pts, p_pts in combined_rows[: max(1, track_limit)]
    ]
    shown = tracked[0] if tracked else None

    if shown:
        why = (
            f"Combined (experimental): {shown['name']} SN{shown['netuid']} — "
            f"timing {shown['timing_pts']:.0f} · peer {shown['peer_pts']:.0f} "
            f"(weights {int(W_TIMING*100)}/{int(W_PEER*100)}). Not a settled claim."
        )
    else:
        why = (
            "Combined (experimental) — no slate yet. "
            "Next up and Peers stay separate; this line needs both axes."
        )

    return {
        "experimental": True,
        "weights": {"timing": W_TIMING, "peer": W_PEER},
        "focus_netuid": int(focus_netuid),
        "trigger": trig,
        "next_up": next_up,
        "peers": peers_payload,
        "combined": shown,
        "tracked": tracked,
        "why": why,
    }


def attach_angles_to_desk(
    payload: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach next_up + combined (+ refresh peers) on hero. Mutates payload."""
    hero = payload.get("hero")
    if not isinstance(hero, dict) or hero.get("netuid") is None:
        return payload
    try:
        netuid = int(hero["netuid"])
    except (TypeError, ValueError):
        return payload

    angles = rank_desk_angles(netuid, state)
    # Peers — keep existing shape on hero
    peers = angles.get("peers") or {}
    hero["peers"] = peers
    hero["lane"] = peers.get("lane")
    hero["signature_rarity"] = peers.get("rarity")
    hero["next_up"] = angles.get("next_up") or []
    hero["combined"] = angles.get("combined")
    hero["combined_experimental"] = True

    payload["peers"] = {
        "focus_netuid": netuid,
        "lane": peers.get("lane"),
        "rarity": peers.get("rarity"),
        "match_count": len(peers.get("matches") or []),
        "why": peers.get("why"),
    }
    payload["next_up"] = angles.get("next_up") or []
    payload["combined"] = {
        "experimental": True,
        "weights": angles.get("weights"),
        "pick": angles.get("combined"),
        "tracked_count": len(angles.get("tracked") or []),
        "why": angles.get("why"),
    }

    try:
        from internal.pump.combined_ledger import maybe_record_combined_call

        maybe_record_combined_call(angles)
    except Exception:
        pass
    return payload
