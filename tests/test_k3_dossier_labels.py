"""K3 dossier presentation — layer labels and weighed-against rows."""

from __future__ import annotations

from fastapi.testclient import TestClient

from internal.learning.dpick_copy import attach_brief_to_daily_pick
from internal.preview.k3_hold import build_k3_hold_preview_context
from server import app


def test_k3_hold_preview_has_dossier_labels():
    with TestClient(app) as client:
        html = client.get("/preview/k3-hold").text
    assert "Weighed against" in html
    assert "Council votes" in html
    assert "Track record" in html
    assert "k3-weighed-row" in html
    assert "FLIP" in html
    assert "graded calls" in html
    assert "published, not curated" in html.lower()


def test_preview_context_shortlist_roles_in_weighed_rows():
    ctx = build_k3_hold_preview_context(type("R", (), {"base_url": "http://test"})())
    daily = attach_brief_to_daily_pick(ctx["daily_pick_stage"])
    shortlist = daily.get("shortlist") or []
    assert shortlist and shortlist[0].get("role")
