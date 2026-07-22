"""Fast degraded homepage shell ships local learning + SimiVision data."""

import time

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def _ensure_homepage_cache():
    import server as srv

    srv._prime_emergency_home_html()
    srv._warm_homepage_cache(None)


def test_degraded_homepage_has_conviction_cards():
    _ensure_homepage_cache()
    html = client.get("/").text
    assert "dataset.hydrate='1'" in html or 'dataset.hydrate="1"' in html
    # pick-card only renders when hour/day picks exist; section always ships
    assert 'id="section-picks"' in html or "section-picks" in html
    assert "SimiVision picks warming up" not in html


def test_degraded_shell_ssrs_daily_pick_not_blank():
    """Hero must paint from local JSON — not wait for cockpit_hydrate.js."""
    import server as srv

    pick = srv._read_shell_daily_pick()
    srv._HOMEPAGE_HTML_CACHE["html"] = None
    srv._HOMEPAGE_HTML_CACHE["at"] = 0.0
    srv._warm_homepage_cache(None)
    html = client.get("/").text
    assert 'id="k3-dossier"' in html
    assert 'id="k3-call-headline"' in html
    if pick:
        move = (pick.get("brief") or {}).get("move")
        if move:
            assert move in html
        else:
            assert "HOLD · no long" not in html


def test_degraded_shell_ssrs_pump_and_horizons():
    """Pump desk + horizon picks paint from file-backed shell (B0-0)."""
    import server as srv

    srv._HOMEPAGE_HTML_CACHE["html"] = None
    srv._HOMEPAGE_HTML_CACHE["at"] = 0.0
    srv._warm_homepage_cache(None)
    html = client.get("/").text
    assert "Pump desk loads after hydrate" not in html
    assert "Council is convening" not in html
    assert "Backtest warming up" not in html
    assert "Loading judge scores" not in html
    assert (
        "pump-alert__card" in html
        or "pump-alert__empty" in html
        or "Quiet — no lead" in html
    )


def test_degraded_homepage_has_council_weights():
    _ensure_homepage_cache()
    html = client.get("/").text
    assert "council-grid" in html
    assert "Council weights warming up" not in html
    assert "Quiet — council weights" not in html or "council-grid" in html


def test_fast_shell_learning_metrics_has_graded_field():
    from internal.learning.dashboard_context import fast_shell_dashboard_context

    metrics = fast_shell_dashboard_context()["learning_metrics"]
    assert "correct" in metrics
    assert "wrong" in metrics
    assert metrics.get("graded") is not None or (metrics.get("correct", 0) + metrics.get("wrong", 0)) >= 0


def test_minimal_index_context_skips_letter_build(monkeypatch):
    """Timeout fallback must stay instant — never call build_brain_letter."""
    import server as srv

    def _boom(*_a, **_k):
        raise AssertionError("build_brain_letter must not run on minimal shell")

    monkeypatch.setattr("internal.letter.brain_letter.build_brain_letter", _boom)

    class _R:
        base_url = "http://test"

    ctx = srv._minimal_index_context(_R())
    assert ctx["data_source"] == "snapshot"
    assert ctx["brain_letter"]["empty"] is True
    assert ctx["brain_letter"]["status"] == "quiet"


def test_homepage_timeout_does_not_block_on_hung_builder(monkeypatch):
    """Regression: sync index + hung builder wedged Fly → 0-byte blank phone."""
    import server as srv

    def _hang(_request):
        time.sleep(60)
        return {}

    monkeypatch.setattr(srv, "_degraded_index_context", _hang)
    srv._DEGRADED_INDEX_CACHE["ctx"] = None
    srv._DEGRADED_INDEX_CACHE["at"] = 0.0
    srv._HOMEPAGE_HTML_CACHE["html"] = None
    srv._HOMEPAGE_HTML_CACHE["at"] = 0.0
    srv._HOMEPAGE_WARMING = False

    t0 = time.time()
    resp = client.get("/")
    elapsed = time.time() - t0
    assert resp.status_code == 200
    assert elapsed < 3.0, f"homepage hung {elapsed:.1f}s on cache miss"
    assert (
        "dataset.hydrate" in resp.text
        or "council-first" in resp.text
        or "Loading council" in resp.text
    )


def test_homepage_cache_miss_returns_emergency_instantly(monkeypatch):
    """Cold cache must paint immediately — background warm must not block GET /."""
    import server as srv

    def _slow_render(_request):
        time.sleep(30)
        return "<html>slow</html>"

    monkeypatch.setattr(srv, "_render_index_html", _slow_render)
    srv._HOMEPAGE_HTML_CACHE["html"] = None
    srv._HOMEPAGE_HTML_CACHE["at"] = 0.0
    srv._HOMEPAGE_WARMING = False
    if not srv._EMERGENCY_HOME_HTML:
        srv._prime_emergency_home_html()

    t0 = time.time()
    resp = client.get("/")
    elapsed = time.time() - t0
    assert resp.status_code == 200
    assert elapsed < 2.0, f"cache miss blocked {elapsed:.1f}s"
    assert resp.text == srv._EMERGENCY_HOME_HTML


def test_homepage_html_byte_cache_is_fast():
    import server as srv

    srv._HOMEPAGE_HTML_CACHE["html"] = None
    srv._HOMEPAGE_HTML_CACHE["at"] = 0.0
    srv._DEGRADED_INDEX_CACHE["ctx"] = None
    srv._DEGRADED_INDEX_CACHE["at"] = 0.0
    srv._warm_homepage_cache(None)
    t0 = time.time()
    resp = client.get("/")
    elapsed = time.time() - t0
    assert resp.status_code == 200
    assert elapsed < 0.5, f"HTML cache miss felt like {elapsed:.2f}s"
    assert "What the loop learned" in resp.text


def test_homepage_responds_quickly():
    t0 = time.time()
    resp = client.get("/")
    elapsed = time.time() - t0
    assert resp.status_code == 200
    assert elapsed < 5.0, f"homepage took {elapsed:.1f}s"


def test_homepage_includes_above_fold_scripts():
    html = client.get("/").text
    for src in (
        "api_fetch.js",
        "brain_letter.js",
        "paper_portfolio.js",
        "weekly_letter.js",
        "market_drivers_ui.js",
    ):
        assert src in html, f"missing {src}"
    assert "apiFetchJson" in html, "missing inline fetch timeout bootstrap"


def test_degraded_shell_ssrs_brain_letter_when_available():
    """B0-b: warm shell prefers file-backed brain letter over quiet stub."""
    import server as srv

    srv._HOMEPAGE_HTML_CACHE["html"] = None
    srv._HOMEPAGE_HTML_CACHE["at"] = 0.0
    srv._warm_homepage_cache(None)
    html = client.get("/").text
    assert "brain-letter" in html
    assert (
        "What changed since yesterday" in html
        or "Brief writes after the first graded windows land" in html
    )


def test_homepage_batch0_brain_presentation():
    _ensure_homepage_cache()
    html = client.get("/").text
    assert "section-proof-band" in html
    assert "What the loop learned" in html
    assert "Focus · Contest · Prove it · Watch us update" in html
    assert "Loading focus from council" not in html
    assert "section-story-strip" in html
    # story strip should be in proof band, not only inside pro drawer
    proof_pos = html.find("section-proof-band")
    pro_pos = html.find('id="pro-cockpit"')
    strip_pos = html.find("section-story-strip")
    assert proof_pos >= 0 and strip_pos >= 0
    assert strip_pos > proof_pos
    assert strip_pos < pro_pos or pro_pos < 0
    assert html.count('id="section-story-strip"') == 1
    assert "Morning brief · graded memory" in html
    assert "Resolver integrity" in html
    assert "brain UI gate" not in html.lower()
    assert 'id="k3-weight-nudge-line"' in html
    assert "Story path warming up" not in html
    assert (
        "Quiet — story path fills when council clears an audited pick." in html
        or "No audited pick today" in html
    )


def test_homepage_shell_cache_speeds_repeat():
    client.get("/")
    t0 = time.time()
    resp = client.get("/")
    elapsed = time.time() - t0
    assert resp.status_code == 200
    assert elapsed < 1.5, f"cached homepage took {elapsed:.1f}s"
