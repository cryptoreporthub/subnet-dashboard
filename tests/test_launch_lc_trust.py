"""Launch LC — legal/trust/SEO surface checks."""

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_robots_txt():
    res = client.get("/robots.txt")
    assert res.status_code == 200
    body = res.text
    assert "Disallow: /api/" in body
    assert "Allow: /" in body


def test_homepage_nfa_disclaimer():
    res = client.get("/pump")
    assert res.status_code == 200
    assert "not financial advice" in res.text.lower()


def test_footer_partial_nfa():
    from server import templates

    html = templates.env.get_template("partials/premium/footer.html").render(
        data_source="snapshot",
        sn_list=[],
        mindmap_trail=[],
        predictions=[],
        degraded=True,
    )
    assert "not financial advice" in html.lower()


def test_homepage_og_share_png():
    res = client.get("/pump")
    assert res.status_code == 200
    assert "og-share.png" in res.text


def test_og_share_static_file():
    res = client.get("/static/og-share.png")
    assert res.status_code == 200
    assert res.headers.get("content-type", "").startswith("image/")


def test_instant_home_shells_include_nfa_and_og_image():
    from internal.instant_bailout import HARDCODED_EMERGENCY_HTML
    import server as srv

    for label, blob in (
        ("instant", srv._INSTANT_HOME_SHELL),
        ("emergency", HARDCODED_EMERGENCY_HTML.decode("utf-8")),
    ):
        lower = blob.lower()
        assert "not financial advice" in lower, label
        assert "og-share.png" in blob, label
        assert 'property="og:image"' in blob, label
