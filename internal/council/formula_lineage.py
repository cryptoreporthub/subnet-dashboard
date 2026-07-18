"""Formula lineage — cited sources, adaptations, and live learning-loop state per lane.

Each council expert and judge documents:
  1. The inspiration (academic / industry source)
  2. Our adapted formula (what actually runs in code)
  3. How soul_map + predictions + mindmap improve weights over time
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.weights import DEFAULT_WEIGHTS, SOUL_MAP_PATH, _load_raw, load_weights

LANE_IDS = (
    "quant",
    "hype",
    "dark_horse",
    "technical",
    "oracle",
    "echo",
    "pulse",
)

# Static registry — honest about conceptual vs literal implementation.
_REGISTRY: Dict[str, Dict[str, Any]] = {
    "quant": {
        "label": "Quant",
        "lane_type": "council_expert",
        "current_formula": {
            "expression": "weighted(apy, emission, staking_yield, registration_cost, …)",
            "implementation": "internal/council/state_vector.py::_expert_contributions",
            "summary": "Fundamental / yield / emission scoring from subnet registry fields.",
        },
        "inspiration": [
            {
                "citation": "López de Prado, M. (2018). Advances in Financial Machine Learning — primary signal layer.",
                "url": "https://www.amazon.com/Advances-Financial-Machine-Learning-Marcos/dp/1119482089",
                "relationship": "framework",
            },
        ],
        "adaptations": [
            "Mapped to Bittensor subnet APY, emission, and staking conviction instead of equities.",
            "Impact scaling via internal/subnets/impact.py for subnet market-cap tilt.",
        ],
    },
    "hype": {
        "label": "Hype",
        "lane_type": "council_expert",
        "current_formula": {
            "expression": "delegation_flow(subnet)",
            "implementation": "internal/council/state_vector.py::_compute_hype_score",
            "summary": "Capital-flow / delegation momentum — delegators voting with TAO.",
        },
        "inspiration": [
            {
                "citation": "Bittensor delegation dynamics — on-chain stake movement as sentiment proxy.",
                "url": "https://docs.bittensor.com/",
                "relationship": "domain",
            },
        ],
        "adaptations": [
            "Uses delegation_flow signal from subnet snapshot instead of social-volume hype.",
        ],
    },
    "dark_horse": {
        "label": "Dark Horse",
        "lane_type": "council_expert",
        "current_formula": {
            "expression": "0.4×pool_score + 0.3×supply_score + 0.3×pe_score",
            "implementation": "internal/council/state_vector.py::_compute_dark_horse_score",
            "summary": (
                "On-chain flow composite: TAO pool depth, supply contraction, "
                "price/emission undervaluation — contrarian / hidden-value lane."
            ),
        },
        "inspiration": [
            {
                "citation": (
                    "Martin, I.W.R. & Shi, R. (2024). Forecasting Crashes with a Smile. "
                    "Stanford Digital Repository."
                ),
                "url": "https://doi.org/10.25740/jj155vj0955",
                "relationship": "conceptual",
                "note": (
                    "Voice-to-text often hears “Irwin”; author is Ian Martin (Stanford). "
                    "Paper derives option-implied crash-probability bounds. We adopt the "
                    "contrarian crash/undervaluation framing, not the literal options formula."
                ),
            },
            {
                "citation": "López de Prado (2018) — meta-label / contrarian overlay on primary signals.",
                "url": "https://docs.jesse.trade/docs/research/ml/meta-labeling",
                "relationship": "framework",
            },
        ],
        "adaptations": [
            "Replaced option-implied crash bounds with TAO pool ratio, supply change, and price/emission ratio (data we have on subnets).",
            "Blend weights 40/30/30 tuned for on-chain Bittensor fields vs Martin-Shi equity options inputs.",
            "Renamed legacy contrarian expert → dark_horse; weights learned via resolver nudges + calibration.",
        ],
    },
    "technical": {
        "label": "Technical",
        "lane_type": "council_expert",
        "current_formula": {
            "expression": "weighted(RSI, MACD, stochastic, momentum, … per horizon)",
            "implementation": "internal/council/state_vector.py + signal_weights in soul_map",
            "summary": "Technical indicator stack with per-signal learned weights.",
        },
        "inspiration": [
            {
                "citation": "Murphy, J.J. Technical Analysis of the Financial Markets (indicator consensus).",
                "url": "https://www.investopedia.com/terms/t/technicalanalysis.asp",
                "relationship": "domain",
            },
        ],
        "adaptations": [
            "Per-signal weights nudged on resolve (internal/council/weights.py nudge_signal_weight).",
            "Hour vs day horizons with separate weight tables in adversarial_state.signal_weights.",
        ],
    },
    "oracle": {
        "label": "Oracle",
        "lane_type": "judge",
        "current_formula": {
            "expression": "0.28 + 0.34×signal + 0.24×direction_match + 0.14×completeness + source_adj",
            "implementation": "internal/judges/oracle_judge.py::evaluate",
            "summary": "Truthfulness / evidentiary quality gate (τ ≥ 0.55 for endorsement).",
        },
        "inspiration": [
            {
                "citation": "López de Prado (2018) Ch. 3 — meta-model gate on primary council pick.",
                "url": "https://docs.jesse.trade/docs/research/ml/meta-labeling",
                "relationship": "framework",
            },
            {
                "citation": "El-Yaniv & Wiener (2010) — selective classification / reject option.",
                "url": "https://jmlr.org/papers/volume11/el-yaniv10a.html",
                "relationship": "evaluation",
            },
        ],
        "adaptations": [
            "signal_source tier adjustments when subnet_snapshot missing from ledger.",
            "Endorsement threshold 0.55 (AFML production band).",
        ],
    },
    "echo": {
        "label": "Echo",
        "lane_type": "judge",
        "current_formula": {
            "expression": "0.35 + 0.4×agreement + 0.15×dominant_match + 0.1×weight_factor",
            "implementation": "internal/judges/echo_judge.py::evaluate",
            "summary": "Consensus / resonance across signal impacts (τ ≥ 0.5).",
        },
        "inspiration": [
            {
                "citation": "Chow, C.K. (1957) — reject when consensus confidence is low.",
                "url": "https://ieeexplore.ieee.org/document/4338785",
                "relationship": "framework",
            },
        ],
        "adaptations": [
            "Council-pick rows penalized (low agreement) — Echo abstains on weak multi-signal consensus.",
            "Expert weight factor from weights_at_creation on each prediction.",
        ],
    },
    "pulse": {
        "label": "Pulse",
        "lane_type": "judge",
        "current_formula": {
            "expression": "0.3 + 0.25×momentum + 0.15×volume + 0.2×impact + 0.1×proportion + alignment",
            "implementation": "internal/judges/pulse_judge.py::evaluate",
            "summary": "Momentum / energy gate (τ ≥ 0.55). Paper P&L scaled 1.3×.",
        },
        "inspiration": [
            {
                "citation": "Jegadeesh & Titman (1993) — momentum factor (price trend persistence).",
                "url": "https://doi.org/10.1111/j.1540-6261.1993.tb04702.x",
                "relationship": "conceptual",
            },
        ],
        "adaptations": [
            "24h price change + volume + strongest signal impact for subnet picks.",
            "Optional Blockmachine on-chain price delta bonus when present.",
        ],
    },
}


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _expert_stats(lane_id: str) -> Dict[str, Any]:
    """Live accuracy + weight from predictions ledger for council experts."""
    out: Dict[str, Any] = {"graded_n": 0, "accuracy": None, "correct": 0, "wrong": 0}
    try:
        from internal.council.resolver import _normalize_expert
        from internal.learning.predictions_store import load_predictions

        for row in load_predictions().get("resolved") or []:
            if row.get("correct") is None or row.get("outcome") in (
                "duplicate",
                "expired",
                "ungradeable",
            ):
                continue
            expert = _normalize_expert(row)
            if expert != lane_id:
                continue
            out["graded_n"] += 1
            if row.get("correct"):
                out["correct"] += 1
            else:
                out["wrong"] += 1
        if out["graded_n"]:
            out["accuracy"] = round(out["correct"] / out["graded_n"], 4)
    except Exception:
        pass
    return out


def _learning_loop_state(lane_id: str, soul_map_path: str = SOUL_MAP_PATH) -> Dict[str, Any]:
    """How soul_map + calibration currently adapt this lane."""
    weights = load_weights(soul_map_path)
    data = _load_raw(soul_map_path)
    adv = data.get("adversarial_state") if isinstance(data.get("adversarial_state"), dict) else {}
    cal = adv.get("calibration") if isinstance(adv.get("calibration"), dict) else {}

    loop: Dict[str, Any] = {
        "feeds": [
            "data/soul_map.json → adversarial_state.council_weights (nudge on resolve)",
            "data/predictions.json → resolved outcomes (grading ledger)",
            "internal/council/mindmap_bridge.py → disposition + trail mirror",
            "internal/calibration/pipeline.py → retrain → cert → fire (when enabled)",
        ],
        "current_weight": weights.get(lane_id) if lane_id in DEFAULT_WEIGHTS else None,
        "last_weight_update": adv.get("last_weight_update"),
        "calibration_last_retrain": cal.get("last_retrain_at"),
        "calibration_status": cal.get("last_cert_status"),
        "stagnant_source_note": (
            "Original papers are fixed; our live weights, signal_weights, and "
            "calibration history adapt from graded picks — each cert-fired version "
            "should beat the prior snapshot on holdout or cert blocks the swap."
        ),
    }
    if lane_id in DEFAULT_WEIGHTS:
        loop.update(_expert_stats(lane_id))
    return loop


def build_lane_lineage(
    lane_id: str,
    *,
    soul_map_path: str = SOUL_MAP_PATH,
) -> Optional[Dict[str, Any]]:
    """Full lineage card for one council expert or judge."""
    base = _REGISTRY.get(lane_id)
    if not base:
        return None
    return {
        "id": lane_id,
        "label": base["label"],
        "lane_type": base["lane_type"],
        "version": "1.0.0",
        "current_formula": base["current_formula"],
        "inspiration": base.get("inspiration", []),
        "adaptations": base.get("adaptations", []),
        "learning_loop": _learning_loop_state(lane_id, soul_map_path=soul_map_path),
        "updated_at": _utcnow_z(),
    }


def build_all_lineage(*, soul_map_path: str = SOUL_MAP_PATH) -> Dict[str, Any]:
    """Catalog of all lanes with live learning state."""
    lanes = [build_lane_lineage(lid, soul_map_path=soul_map_path) for lid in LANE_IDS]
    return {
        "status": "ok",
        "summary": (
            "Each lane cites its intellectual source, documents our adaptations, "
            "and reports live learning-loop state from soul_map + predictions."
        ),
        "lanes": [lane for lane in lanes if lane],
        "updated_at": _utcnow_z(),
    }
