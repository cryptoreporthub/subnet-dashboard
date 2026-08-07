"""Tribunal hero preview route — SSR fixture assertions (Council Hero v4)."""

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_gated_preview_has_hero_and_three_judges():
    r = client.get("/preview/tribunal?state=gated")
    assert r.status_code == 200
    html = r.text
    assert "tribunal-hero" in html
    assert html.count('data-judge="oracle"') == 1
    assert html.count('data-judge="echo"') == 1
    assert html.count('data-judge="pulse"') == 1
    assert "tribunal-hero__puffs" in html
    assert "tribunal-hero__rays" in html
    assert 'data-panel="decision-log"' not in html
    assert 'data-panel="accuracy-ledger"' not in html
    assert 'data-metric="avg_accuracy"' in html
    assert 'data-metric="signal_score"' in html
    assert "tribunal-hero__metrics" in html
    assert "feTurbulence" not in html
    assert "33.6%" in html
    assert "GATED · HOLD" in html
    assert "SN99" in html
    assert "THE TRIBUNAL" not in html
    assert html.count("data-last5 hidden") == 3

def test_sealed_label_is_long_not_buy():
    r = client.get("/preview/tribunal?state=sealed")
    assert r.status_code == 200
    html = r.text
    assert "SEALED · LONG" in html
    assert "SEALED · BUY" not in html
    assert "SN14 · TaoHash" in html
    assert "THE TRIBUNAL" not in html
    assert "LAST 5" not in html or "data-last5 hidden" in html
    assert 'data-metric="win_rate"' in html


def test_forming_and_cold_have_no_fake_71_percent():
    for state in ("forming", "cold"):
        r = client.get(f"/preview/tribunal?state={state}")
        assert r.status_code == 200
        html = r.text
        assert "71%" not in html
        assert "THE TRIBUNAL" not in html
        assert "Awaiting subnet" in html
        if state == "forming":
            assert "FORMING" in html
        else:
            assert "COLD" in html


def test_all_states_return_200_with_distinct_labels():
    labels = {}
    for state in ("sealed", "gated", "forming", "cold"):
        r = client.get(f"/preview/tribunal?state={state}")
        assert r.status_code == 200
        if state == "sealed":
            labels[state] = "SEALED · LONG"
        elif state == "gated":
            labels[state] = "GATED · HOLD"
        elif state == "forming":
            labels[state] = "FORMING"
        else:
            labels[state] = "COLD"
        assert labels[state] in r.text
    assert len(set(labels.values())) == 4


def test_metrics_strip_renders_six_cells():
    r = client.get("/preview/tribunal?state=gated")
    assert r.status_code == 200
    html = r.text
    assert "tribunal-hero__metrics" in html
    for key in ("avg_accuracy", "win_rate", "signal_score", "rsi", "stochastic", "price_7d"):
        assert 'data-metric="' + key + '"' in html
