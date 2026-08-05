"""§28 — shareable product pages and search."""
from fastapi.testclient import TestClient

from server import app

client = TestClient(app)

WALLET = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"


def test_subnet_share_page_returns_200():
    resp = client.get("/subnet/1")
    assert resp.status_code == 200
    assert "SN1" in resp.text or "Subnet" in resp.text
    assert "og:title" in resp.text


def test_wallet_share_page_returns_200():
    resp = client.get(f"/wallet/{WALLET}")
    assert resp.status_code == 200
    assert WALLET[:10] in resp.text
    assert "Wallet" in resp.text


def test_global_search_subnet_numeric():
    resp = client.get("/api/search?q=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    urls = [r["url"] for r in data.get("results") or []]
    assert "/subnet/1" in urls


def test_markdown_subset_html_escapes():
    from internal.analytics.report import markdown_subset_html

    html_out = markdown_subset_html("# Hello\n- **bold** <script>")
    assert "<script>" not in html_out
    assert "<strong>bold</strong>" in html_out


def test_subnet_share_page_partial_on_report_timeout(monkeypatch):
    import internal.share_pages.routes as share_routes

    async def _partial_report(netuid):
        return share_routes._partial_subnet_report(netuid, reason="report timeout"), "report_timeout"

    async def _fast_explain(_netuid):
        return {"verdict": "not_today_pick", "blockers": []}, None

    monkeypatch.setattr(share_routes, "_timed_subnet_report", _partial_report)
    monkeypatch.setattr(share_routes, "_timed_explain_subnet", _fast_explain)

    resp = client.get("/subnet/9")
    assert resp.status_code == 200
    assert "partial" in resp.text.lower() or "still loading" in resp.text.lower()
