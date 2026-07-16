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
        "share_image_png_url": f"/api/predictions/capsule/{pid}/og.png",
        "share_page_url": f"/share/call/{pid}",
    }


def _og_verdict(pred: Dict[str, Any]) -> Tuple[str, str, Tuple[int, int, int]]:
    correct = pred.get("correct")
    if correct is True:
        return "HIT", "#00ff41", (0, 255, 65)
    if correct is False:
        return "MISS", "#f87171", (248, 113, 113)
    return "GRADED", "#8a9a8e", (138, 154, 142)


def _og_move_line(pred: Dict[str, Any]) -> str:
    predicted = pred.get("predicted_pct")
    actual = pred.get("actual_pct")
    if predicted is not None and actual is not None:
        return f"Expected {float(predicted):+.1f}% → Actual {float(actual):+.1f}%"
    return ""


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
    verdict, v_color, v_rgb = _og_verdict(pred)
    v_stroke = f"rgba({v_rgb[0]},{v_rgb[1]},{v_rgb[2]},0.45)"

    statement = _truncate(pred.get("statement"))
    tags = _og_tags(pred)
    move = _og_move_line(pred)

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


def _load_og_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for root in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF"):
        try:
            return ImageFont.truetype(f"{root}/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_og_png(pred: Dict[str, Any]) -> bytes:
    """1200×630 OG card PNG for social crawlers (§23 S23-1)."""
    from io import BytesIO

    from PIL import Image, ImageDraw

    name = pred.get("name") or f"SN{pred.get('netuid', '?')}"
    verdict, _, v_rgb = _og_verdict(pred)
    move = _og_move_line(pred)
    statement = _truncate(pred.get("statement"))
    tags = _og_tags(pred)

    img = Image.new("RGB", (_OG_W, _OG_H), (10, 10, 10))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, _OG_W, _OG_H), fill=(0, 26, 13))
    draw.rounded_rectangle((48, 48, 1152, 582), radius=24, fill=(0, 40, 20), outline=(0, 255, 65), width=2)

    font_brand = _load_og_font(20)
    font_name = _load_og_font(56, bold=True)
    font_move = _load_og_font(34, bold=True)
    font_stmt = _load_og_font(26)
    font_verdict = _load_og_font(24, bold=True)
    font_tag = _load_og_font(18)
    font_foot = _load_og_font(18)

    draw.text((72, 88), "SIMIVISION · GRADED CALL", fill=(138, 154, 142), font=font_brand)
    draw.text((72, 150), str(name)[:40], fill=(232, 240, 233), font=font_name)
    draw.rounded_rectangle((940, 168, 1100, 220), radius=12, fill=(0, 0, 0), outline=v_rgb, width=2)
    vb = draw.textbbox((0, 0), verdict, font=font_verdict)
    vw = vb[2] - vb[0]
    draw.text((1020 - vw // 2, 178), verdict, fill=v_rgb, font=font_verdict)

    y = 300
    if move:
        draw.text((72, y), move, fill=(232, 240, 233), font=font_move)
        y += 52
    if statement:
        draw.text((72, y), statement, fill=(232, 240, 233), font=font_stmt)
        y += 44

    x = 72
    for label, color_hex in tags:
        try:
            tag_rgb = tuple(int(color_hex.strip("#")[i : i + 2], 16) for i in (0, 2, 4))
        except Exception:
            tag_rgb = (138, 154, 142)
        w = max(88, len(label) * 10 + 28)
        draw.rounded_rectangle((x, 430, x + w, 464), radius=17, fill=(0, 0, 0), outline=tag_rgb, width=1)
        draw.text((x + 14, 438), label, fill=tag_rgb, font=font_tag)
        x += w + 12

    draw.text(
        (72, 540),
        "Direction graded on token price — staking APY is income, not price.",
        fill=(138, 154, 142),
        font=font_foot,
    )

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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
    demo_pred = {
        "name": "Demo",
        "predicted_pct": 1.0,
        "actual_pct": 2.0,
        "correct": True,
        "statement": "Self-check graded call",
    }
    demo = build_og_svg(demo_pred)
    assert "HIT" in demo and "Demo" in demo
    png = build_og_png(demo_pred)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    print("prediction_capsule self-check ok")
