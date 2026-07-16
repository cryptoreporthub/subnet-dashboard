"""§21 L12 — time-capsule replay: full prediction snapshot by id."""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Tuple

_SKIP = frozenset({"duplicate", "expired", "ungradeable"})
_OG_W = 1200
_OG_H = 630


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _truncate(text: Any, max_len: int = 140) -> str:
    s = str(text or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def capsule_share_urls(prediction_id: str) -> Dict[str, str]:
    pid = str(prediction_id)
    return {
        "share_image_url": f"/api/predictions/capsule/{pid}/og.svg",
        "share_page_url": f"/share/call/{pid}",
    }


def _find_prediction(prediction_id: str) -> Optional[Dict[str, Any]]:
    from internal.learning.predictions_store import load_predictions

    data = load_predictions()
    for bucket in ("resolved", "predictions"):
        for pred in data.get(bucket) or []:
            if isinstance(pred, dict) and str(pred.get("id") or "") == str(prediction_id):
                row = dict(pred)
                row["_bucket"] = bucket
                return row
    return None


def build_share_card(pred: Dict[str, Any]) -> str:
    """Plain-text graded call card for clipboard share (§21 L14 lite)."""
    name = pred.get("name") or f"SN{pred.get('netuid', '?')}"
    predicted = pred.get("predicted_pct")
    actual = pred.get("actual_pct")
    outcome = "✓" if pred.get("correct") else "✗" if pred.get("correct") is False else "?"
    lines = [
        f"SimiVision graded call — {name}",
        f"Prediction: {pred.get('statement') or '—'}",
    ]
    if predicted is not None and actual is not None:
        lines.append(f"Expected {float(predicted):+.1f}% → actual {float(actual):+.1f}% {outcome}")
    snap = pred.get("subnet_snapshot") if isinstance(pred.get("subnet_snapshot"), dict) else {}
    if snap.get("yield_trap"):
        lines.append("Context: yield trap (high APY, falling token)")
    driver = snap.get("return_driver") or snap.get("dominant_driver")
    if driver:
        lines.append(f"Driver: {str(driver).replace('_', ' ')}")
    lines.append("— subnet-dashboard / SimiVision learning loop")
    return "\n".join(lines)


def _og_tags(pred: Dict[str, Any]) -> List[Tuple[str, str]]:
    snap = pred.get("subnet_snapshot") if isinstance(pred.get("subnet_snapshot"), dict) else {}
    tags: List[Tuple[str, str]] = []
    if snap.get("yield_trap"):
        tags.append(("yield trap", "#f59e0b"))
    price_7d = snap.get("price_change_7d")
    if price_7d is not None and abs(float(price_7d)) >= 1:
        v = float(price_7d)
        tags.append((f"price 7d {v:+.0f}%", "#8a9a8e"))
    driver = snap.get("return_driver") or snap.get("dominant_driver")
    if driver:
        tags.append((str(driver).replace("_", " "), "#8a9a8e"))
    return tags[:3]


def build_og_svg(pred: Dict[str, Any]) -> str:
    """1200×630 OG card — stdlib SVG, no image deps (§22 S22-3)."""
    name = pred.get("name") or f"SN{pred.get('netuid', '?')}"
    correct = pred.get("correct")
    if correct is True:
        verdict, v_color, v_stroke = "HIT", "#00ff41", "rgba(0,255,65,0.45)"
    elif correct is False:
        verdict, v_color, v_stroke = "MISS", "#f87171", "rgba(248,113,113,0.45)"
    else:
        verdict, v_color, v_stroke = "GRADED", "#8a9a8e", "rgba(138,154,142,0.45)"

    predicted = pred.get("predicted_pct")
    actual = pred.get("actual_pct")
    move = ""
    if predicted is not None and actual is not None:
        move = f"Expected {float(predicted):+.1f}% → Actual {float(actual):+.1f}%"

    statement = _truncate(pred.get("statement"))
    tags = _og_tags(pred)

    tag_svg = []
    x = 72
    for label, color in tags:
        w = max(88, len(label) * 9 + 28)
        tag_svg.append(
            f'<rect x="{x}" y="430" width="{w}" height="34" rx="17" '
            f'fill="rgba(0,0,0,0.35)" stroke="{color}" stroke-width="1" opacity="0.95"/>'
            f'<text x="{x + 14}" y="452" fill="{color}" font-family="monospace" '
            f'font-size="18">{_esc(label)}</text>'
        )
        x += w + 12

    stmt_block = ""
    if statement:
        stmt_block = (
            f'<text x="72" y="390" fill="#e8f0e9" font-family="system-ui,sans-serif" '
            f'font-size="26">{_esc(statement)}</text>'
        )

    move_block = ""
    if move:
        move_block = (
            f'<text x="72" y="330" fill="#e8f0e9" font-family="system-ui,sans-serif" '
            f'font-size="34" font-weight="600">{_esc(move)}</text>'
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{_OG_W}" height="{_OG_H}" viewBox="0 0 {_OG_W} {_OG_H}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#001a0d"/>
      <stop offset="100%" stop-color="#0a0a0a"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="url(#bg)"/>
  <rect x="48" y="48" width="1104" height="534" rx="24" fill="rgba(0,40,20,0.55)"
        stroke="rgba(0,255,65,0.35)" stroke-width="2"/>
  <text x="72" y="108" fill="#8a9a8e" font-family="monospace" font-size="20"
        letter-spacing="3">SIMIVISION · GRADED CALL</text>
  <text x="72" y="210" fill="#e8f0e9" font-family="system-ui,sans-serif" font-size="56"
        font-weight="700">{_esc(name)}</text>
  <rect x="940" y="168" width="160" height="52" rx="12" fill="rgba(0,0,0,0.35)"
        stroke="{v_stroke}" stroke-width="2"/>
  <text x="1020" y="204" fill="{v_color}" font-family="monospace" font-size="24"
        font-weight="700" text-anchor="middle">{verdict}</text>
  {move_block}
  {stmt_block}
  {''.join(tag_svg)}
  <text x="72" y="560" fill="#8a9a8e" font-family="system-ui,sans-serif" font-size="18">
    Direction graded on token price — staking APY is income, not price.
  </text>
</svg>"""


def get_prediction_capsule(prediction_id: str) -> Dict[str, Any]:
    """Return full prediction + replay capsule for time-travel UI."""
    pred = _find_prediction(prediction_id)
    if not pred:
        return {"status": "not_found", "reason": "unknown_id"}

    snap = pred.get("subnet_snapshot") if isinstance(pred.get("subnet_snapshot"), dict) else {}
    bucket = pred.pop("_bucket", None)
    gradeable = pred.get("outcome") not in _SKIP and pred.get("actual_pct") is not None

    return {
        "status": "success",
        "prediction_id": prediction_id,
        "bucket": bucket,
        "gradeable": gradeable,
        "prediction": pred,
        "capsule": {
            "statement": pred.get("statement"),
            "expert": pred.get("expert"),
            "horizon_type": pred.get("horizon_type"),
            "created_at": pred.get("created_at"),
            "resolved_at": pred.get("resolved_at"),
            "predicted_pct": pred.get("predicted_pct"),
            "actual_pct": pred.get("actual_pct"),
            "correct": pred.get("correct"),
            "subnet_snapshot": snap,
            "active_signals": pred.get("active_signals"),
            "weights_at_creation": pred.get("weights_at_creation"),
            "judge_scores_at_creation": pred.get("judge_scores_at_creation"),
            "learning_state_at_creation": pred.get("learning_state_at_creation"),
        },
        "share_text": build_share_card(pred),
        **capsule_share_urls(prediction_id),
    }


if __name__ == "__main__":
    demo = build_og_svg(
        {
            "name": "Demo",
            "predicted_pct": 1.0,
            "actual_pct": 2.0,
            "correct": True,
            "statement": "Self-check graded call",
        }
    )
    assert "HIT" in demo and "Demo" in demo
    print("prediction_capsule self-check ok")
