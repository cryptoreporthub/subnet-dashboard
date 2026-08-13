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
    assert 'data-panel="decision-log"' in html
    assert 'data-panel="accuracy-ledger"' in html
    assert 'data-panel="jury-move"' in html
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
    assert "LAST 5" in html
    assert "data-last5 hidden" not in html
    assert 'data-council-last5' in html
    assert 'data-council-last5 hidden' not in html


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


def test_row_three_alignment_hidden():
    r = client.get("/preview/tribunal?state=gated")
    assert r.status_code == 200
    assert 'data-metric="alignment"' in r.text
    assert "hidden" in r.text.split('data-metric="alignment"')[1].split(">")[0]


def test_eye_ring_shared_origin_no_scale_squash():
    from pathlib import Path

    html = Path("templates/partials/premium/tribunal_hero.html").read_text(encoding="utf-8")
    css = Path("static/css/tribunal-hero-layout.css").read_text(encoding="utf-8")
    preview = client.get("/preview/tribunal?state=gated").text
    assert "tribunal-hero__ring" in html
    assert 'class="tribunal-hero__ring"' in preview
    assert "data-eye-path" in preview
    assert "data-glass-ring" in preview
    assert "scaleY(.62)" not in css
    assert "scaleY(.62)" not in html
    assert "feTurbulence" not in html
    assert preview.count('data-instrument') == 1
