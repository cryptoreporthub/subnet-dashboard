"""Staking APY SSR — one conversion via subnet_apy_percent(); bare em-dash when missing.

Conversion-direction evidence (do not *100 again in the template):
- internal/subnets/apy.py treats staking_data.apy with from_fraction=True
  (0.18 → 18.0); see tests/test_cockpit_data_fixes.py.
- static/js/cockpit_hydrate.js documents: "Registry staking_data.apy is 0–1".
- report/market_drivers already call subnet_apy_percent for staking_yield_apy.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from internal.subnets.apy import subnet_apy_percent
from server import templates as server_templates


TEMPLATE = "partials/premium/staking.html"


def _render(sn_list, *, degraded: bool = False) -> str:
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["shorten"] = server_templates.env.filters["shorten"]
    env.globals["subnet_apy_percent"] = subnet_apy_percent
    return env.get_template(TEMPLATE).render(
        sn_list=sn_list,
        degraded=degraded,
    )


def test_staking_apy_normal_fraction_converted_once():
    """staking_data.apy fraction 0.247 → display 24.70% (single *100)."""
    sn = {
        "netuid": 12,
        "name": "Compute",
        "emission": 3.0,
        "staking_data": {"apy": 0.247, "total_stake": 1_000_000},
    }
    assert subnet_apy_percent(sn) == 24.7
    html = _render([sn])
    assert "24.70%" in html
    assert "2470" not in html  # no double *100
    assert "\u2014%" not in html


def test_staking_apy_zero_renders_zero_percent():
    sn = {
        "netuid": 1,
        "name": "ZeroYield",
        "emission": 1.0,
        "staking_data": {"apy": 0.0, "total_stake": 100},
    }
    assert subnet_apy_percent(sn) == 0.0
    html = _render([sn])
    assert "0.00%" in html
    assert "\u2014%" not in html


def test_staking_apy_none_missing_is_bare_emdash():
    sn = {
        "netuid": 99,
        "name": "NoApy",
        "emission": 2.0,
        "staking_data": {"total_stake": 50},
    }
    assert subnet_apy_percent(sn) is None
    html = _render([sn])
    assert "\u2014%" not in html
    # value cell is bare em-dash (no trailing %)
    assert 'accent-bright">\u2014</div>' in html or 'accent-bright">—</div>' in html
    assert "0.00%" not in html


def test_staking_template_no_inline_star_100():
    """Guard: template must not re-multiply; conversion lives in subnet_apy_percent()."""
    src = Path("templates/partials/premium/staking.html").read_text(encoding="utf-8")
    assert "subnet_apy_percent" in src
    assert "* 100" not in src
    assert "*100" not in src


def test_server_exposes_subnet_apy_percent_jinja_global():
    assert server_templates.env.globals.get("subnet_apy_percent") is subnet_apy_percent
