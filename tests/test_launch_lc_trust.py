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
