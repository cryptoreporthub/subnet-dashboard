#!/usr/bin/env python3
"""Patch: Fix hourly pick scoring + add conviction ring UI. Idempotent."""
import re

def patch_server_py():
    with open("server.py", "r") as f:
        c = f.read()
    changed = False

    # 1. Add select_hourly_pick import
    if "from internal.council.hourly_pick import select_hourly_pick" not in c:
        anchor = '    def get_or_create_today_pick(*_args, **_kwargs):\n        return {}\n'
        if anchor in c:
            imp = '\ntry:\n    from internal.council.hourly_pick import select_hourly_pick\n'
            imp += 'except Exception:  # pragma: no cover\n    def select_hourly_pick(*_args, **_kwargs):\n'
            imp += '        return {"subnet": None, "score": 0.0, "confidence": 0.0,\n'
            imp += '                "expert_contributions": {}, "scenario_tags": {},\n'
            imp += '                "audit": {"approved": False, "concerns": ["hourly_pick unavailable"],\n'
            imp += '                          "adjusted_confidence": 0.0},\n'
            imp += '                "final_confidence": 0.0, "action": "long"}\n'
            c = c.replace(anchor, anchor + imp, 1)
            changed = True
            print("  [OK] Added select_hourly_pick import")
        else:
            print("  [WARN] Could not find import anchor")
    else:
        print("  [SKIP] Import already present")

    # 2. Replace FIRST get_or_create_today_pick call (hour endpoint)
    if "select_hourly_pick(subnets, market_context)" not in c:
        old = '        _dp_raw = get_or_create_today_pick(subnets, market_context)\n'
        old += '        day_pick = _dp_raw.get("pick") if isinstance(_dp_raw, dict) and _dp_raw.get("pick") else _dp_raw'
        new = '        _hour_result = select_hourly_pick(subnets, market_context)\n'
        new += '        day_pick = _hour_result if _hour_result else _highest_emission_pick(subnets)'
        if old in c:
            c = c.replace(old, new, 1)
            changed = True
            print("  [OK] Replaced hour endpoint with select_hourly_pick")
        else:
            print("  [WARN] Hour endpoint pattern not found")
    else:
        print("  [SKIP] Hour endpoint already patched")

    if changed:
        with open("server.py", "w") as f:
            f.write(c)

def patch_template():
    with open("templates/index.html", "r") as f:
        c = f.read()
    changed = False

    # 1. Add conviction ring CSS before </style>
    if ".conviction-ring" not in c:
        css = '\n.conviction-ring {\n'
        css += '  width: 56px; height: 56px; border-radius: 50%;\n'
        css += '  background: conic-gradient(var(--ring-color, #f59e0b) calc(var(--ring-pct, 0) * 1%), rgba(255,255,255,0.06) 0);\n'
        css += '  display: flex; align-items: center; justify-content: center; position: relative; flex-shrink: 0;\n'
        css += '}\n'
        css += '.conviction-ring::before {\n'
        css += '  content: ""; position: absolute; inset: 4px; border-radius: 50%;\n'
        css += '  background: var(--bg-card, #0a0e0a);\n'
        css += '}\n'
        css += '.conviction-pct { position: relative; z-index: 1; font-size: 11px; font-weight: 700; }\n'
        css += '.conviction-ring-wrap { display: flex; align-items: center; gap: 10px; }\n'
        if "</style>" in c:
            c = c.replace("</style>", css + "</style>", 1)
            changed = True
            print("  [OK] Added conviction ring CSS")
        else:
            print("  [WARN] No </style> tag found")
    else:
        print("  [SKIP] Ring CSS already present")

    # 2. Replace SimiVision CONVICTION badge with ring chart
    badge_pat = r'<span class="badge[^"]*"[^>]*>CONVICTION {{ p\.conviction }}%</span>'
    ring_html = '<div class="conviction-ring-wrap">'
    ring_html += '<div class="conviction-ring" style="--ring-pct: {{ p.conviction }}; '
    ring_html += "--ring-color: {% if p.conviction > 70 %}#22c55e{% elif p.conviction > 40 %}#f59e0b{% else %}#ef4444{% endif %};\">"
    ring_html += '<span class="conviction-pct">{{ p.conviction }}%</span>'
    ring_html += '</div>'
    ring_html += '<span class="badge {% if p.recommendation == \'BUY\' %}badge-buy{% elif p.recommendation == \'HOLD\' %}badge-hold{% elif p.recommendation == \'SELL\' %}badge-sell{% else %}badge-watch{% endif %}">{{ p.recommendation }}</span>'
    ring_html += '</div>'
    new_c, n = re.subn(badge_pat, ring_html, c)
    if n > 0:
        c = new_c
        changed = True
        print(f"  [OK] Replaced {n} conviction badge(es) with ring chart")
    else:
        print("  [SKIP] Conviction badge pattern not found")

    # 3. Replace hero card FINAL CONFIDENCE stat with ring
    hero_pat = r'<div class="hero-stat"><div class="k">FINAL CONFIDENCE</div><div class="v mono">{{ '
    hero_pat += r"%.0f'\|format\(daily_pick\.final_confidence\*100\) }}%</div></div>'
    hero_ring = '<div class="hero-stat"><div class="k">FINAL CONFIDENCE</div>'
    hero_ring += '<div class="conviction-ring" style="--ring-pct: {{ (daily_pick.final_confidence*100)|round }}; '
    hero_ring += "--ring-color: {% if daily_pick.final_confidence > 0.7 %}#22c55e{% elif daily_pick.final_confidence > 0.4 %}#f59e0b{% else %}#ef4444{% endif %};\">"
    hero_ring += '<span class="conviction-pct">{{ \'%.0f\'|format(daily_pick.final_confidence*100) }}%</span>'
    hero_ring += '</div></div>'
    new_c, n = re.subn(hero_pat, hero_ring, c)
    if n > 0:
        c = new_c
        changed = True
        print(f"  [OK] Replaced {n} hero card confidence stat(s) with ring")
    else:
        print("  [SKIP] Hero card pattern not found")

    if changed:
        with open('templates/index.html', 'w') as f:
            f.write(c)
        print('  [OK] Template saved')

if __name__ == "__main__":
    print("Patching server.py...")
    patch_server_py()
    print("Patching templates/index.html...")
    patch_template()
    print("Done!")