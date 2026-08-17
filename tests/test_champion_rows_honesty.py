"""Champion podium must not fabricate strike-rate / hit stats."""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader


def _render_champion_rows(rows):
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    macro = env.get_template("partials/premium/message_intel_ssr_macros.html").module
    return macro.champion_rows(rows)


def test_champion_rows_no_demo_fallback_when_hit_rate_missing():
    html = _render_champion_rows([
        {
            "author_id": "id:1",
            "author_username": "pepeleplutus",
            "author_name": "Gavin",
            "initials": "G",
            "message_count": 3,
            "subnet_count": 0,
            "influence_score": 9.6,
            "graded": 0,
            "hits": 0,
            "hit_rate": None,
            "strike_rate_pct": 100.0,
            "stats_source": "author_reliability",
            "caution": True,
            "receipt_friendly": {"available": False, "graded": 0},
        }
    ])
    assert "88.0%" not in html
    assert "2 verified hits" not in html
    assert "0 verified hits" in html
    assert "100.0%" in html
    assert "No subnet-call receipts" in html


def test_champion_rows_uses_real_subnet_count():
    html = _render_champion_rows([
        {
            "author_id": "id:2",
            "author_name": "Hettie",
            "initials": "H",
            "message_count": 37,
            "subnet_count": 0,
            "influence_score": 9.4,
            "graded": 0,
            "hits": 0,
            "hit_rate": None,
            "strike_rate_pct": None,
            "receipt_friendly": {"available": False, "graded": 0},
        }
    ])
    assert "3 subnets" not in html
    assert "0 subnets" in html
    assert "37 calls" in html
