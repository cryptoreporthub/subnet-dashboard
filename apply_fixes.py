#!/usr/bin/env python3
"""Patch: fix hourly pick scoring + add conviction ring UI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_text(rel):
    return (ROOT / rel).read_text()


def write_text(rel, text):
    (ROOT / rel).write_text(text)


def patch_server_py():
    c = read_text("server.py")
    changed = False

    import_anchor = (
        "try:
"
        "    from internal.council.daily_pick_engine import get_or_create_today_pick
"
        "except Exception:  # pragma: no cover
"
        "    def get_or_create_today_pick(*_args, **_kwargs):
"
        "        return {}
"
    )
    if "from internal.council.hourly_pick import select_hourly_pick" not in c and import_anchor in c:
        hourly_import = (
            "
try:
"
            "    from internal.council.hourly_pick import select_hourly_pick
"
            "except Exception:  # pragma: no cover
"
            "    def select_hourly_pick(*_args, **_kwargs):
"
            "        return {"subnet": None, "score": 0.0, "confidence": 0.0, "expert_contributions": {}, "scenario_tags": {}, "audit": {"approved": False, "concerns": ["hourly_pick unavailable"], "adjusted_confidence": 0.0}, "final_confidence": 0.0, "action": "long"}
"
        )
        c = c.replace(import_anchor, import_anchor + hourly_import, 1)
        changed = True
        print("[OK] added hourly pick import")

    old = (
        '        _dp_raw = get_or_create_today_pick(subnets, market_context)
'
        '        day_pick = _dp_raw.get("pick") if isinstance(_dp_raw, dict) and _dp_raw.get("pick") else _dp_raw'
    )
    new = (
        '        _hour_result = select_hourly_pick(subnets, market_context)
'
        '        day_pick = _hour_result if _hour_result else _highest_emission_pick(subnets)'
    )
    if old in c:
        c = c.replace(old, new, 1)
        changed = True
        print("[OK] rewired hour endpoint")
    else:
        print("[SKIP] hour endpoint pattern not found")

    if changed:
        write_text("server.py", c)


def patch_template():
    c = read_text("templates/index.html")
    changed = False

    css = """
.conviction-ring {
  width: 56px; height: 56px; border-radius: 50%;
  background: conic-gradient(var(--ring-color, #f59e0b) calc(var(--ring-pct, 0) * 1%), rgba(255,255,255,0.06) 0);
  display: flex; align-items: center; justify-content: center; position: relative; flex-shrink: 0;
}
.conviction-ring::before {
  content: ""; position: absolute; inset: 4px; border-radius: 50%;
  background: var(--bg-card, #0a0e0a);
}
.conviction-pct { position: relative; z-index: 1; font-size: 11px; font-weight: 700; }
.conviction-ring-wrap { display: flex; align-items: center; gap: 10px; }
"""
    if ".conviction-ring" not in c and "</style>" in c:
        c = c.replace("</style>", css + "
</style>", 1)
        changed = True
        print("[OK] added conviction ring CSS")

    old_badge = '<span class="badge {% if p.recommendation == 'BUY' %}badge-buy{% elif p.recommendation == 'HOLD' %}badge-hold{% elif p.recommendation == 'SELL' %}badge-sell{% else %}badge-watch{% endif %}">CONVICTION {{ p.conviction }}%</span>'
    new_badge = (
        '<div class="conviction-ring-wrap">'
        '<div class="conviction-ring" style="--ring-pct: {{ p.conviction }}; --ring-color: {% if p.conviction > 70 %}#22c55e{% elif p.conviction > 40 %}#f59e0b{% else %}#ef4444{% endif %};">'
        '<span class="conviction-pct">{{ p.conviction }}%</span>'
        '</div>'
        '<span class="badge {% if p.recommendation == 'BUY' %}badge-buy{% elif p.recommendation == 'HOLD' %}badge-hold{% elif p.recommendation == 'SELL' %}badge-sell{% else %}badge-watch{% endif %}">{{ p.recommendation }}</span>'
        '</div>'
    )
    if old_badge in c:
        c = c.replace(old_badge, new_badge, 1)
        changed = True
        print("[OK] replaced SimiVision conviction badge")

    old_hero = """<div class="hero-stat"><div class="k">FINAL CONFIDENCE</div><div class="v mono">{{ '%.0f'|format(daily_pick.final_confidence*100) }}%</div></div>"""
    new_hero = (
        '<div class="hero-stat"><div class="k">FINAL CONFIDENCE</div>'
        '<div class="conviction-ring" style="--ring-pct: {{ (daily_pick.final_confidence*100)|round }}; --ring-color: {% if daily_pick.final_confidence > 0.7 %}#22c55e{% elif daily_pick.final_confidence > 0.4 %}#f59e0b{% else %}#ef4444{% endif %};">'
        '<span class="conviction-pct">{{ '%.0f'|format(daily_pick.final_confidence*100) }}%</span>'
        '</div></div>'
    )
    if old_hero in c:
        c = c.replace(old_hero, new_hero, 1)
        changed = True
        print("[OK] replaced hero confidence stat")

    if changed:
        write_text("templates/index.html", c)


if __name__ == "__main__":
    patch_server_py()
    patch_template()
    print("done")
