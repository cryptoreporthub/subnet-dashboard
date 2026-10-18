"""§17.F1/F2 — home watchlist + conviction alert UI."""

from __future__ import annotations

from fastapi.testclient import TestClient

from internal.analytics.home_habit import conviction_alerts_snapshot, watchlist_snapshot
from internal.council.publish_gate import publish_gate_label
from internal.preview.tribunal_hero import build_tribunal_view
from internal.watchlist import store as watchlist_store
import server as srv
from server import app


def test_watchlist_snapshot_empty(monkeypatch, tmp_path):
    path = tmp_path / "watchlist.json"
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(path))
    snap = watchlist_snapshot()
    assert snap["status"] == "ok"
    assert snap["netuids"] == []
    assert snap["count"] == 0


def test_index_home_habit_controls():
    srv._prime_emergency_home_html()
    srv._warm_homepage_cache(None)
    with TestClient(app) as client:
        html = client.get("/").text
    assert "habit-pin-btn" in html
    assert "section-living-focus" in html or "In motion" in html


def test_hybrid_trust_snapshot_shape():
    from internal.analytics.home_habit import hybrid_trust_snapshot

    snap = hybrid_trust_snapshot()
    assert "ready" in snap
    assert "n" in snap
    assert snap.get("reason") in (None, "not_enough_data", "error")
    if snap.get("accuracy") is not None:
        assert 0.0 <= float(snap["accuracy"]) <= 1.0


def test_council_stage_learning_accuracy_uses_fraction():
    """Regression: trust_banner accuracy is 0–1; template must not show 0.3% as 0.3%."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.globals["publish_gate_label"] = publish_gate_label
    tmpl = env.get_template("partials/premium/council_stage.html")
    dpick = {"action": "HOLD", "pick": None, "candidate": None}
    trust = {
        "graded": 454,
        "correct": 143,
        "wrong": 311,
        "accuracy": 0.315,
        "ready": True,
    }
    html = tmpl.render(
        dpick=dpick,
        hybrid_trust={"n": 454},
        trust_banner=trust,
        story_path={},
        habit_watchlist={},
        habit_alerts={"enabled": False},
        tribunal=build_tribunal_view(dpick, {"trust_banner": trust}),
    )
    assert "31.5%" in html or "31.4%" in html or "31.6%" in html
    assert "0.3%" not in html


def test_pin_button_updates_watchlist(monkeypatch, tmp_path):
    path = tmp_path / "watchlist.json"
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(path))
    client = TestClient(app)
    put = client.put("/api/watchlist", json={"netuids": [12]})
    assert put.status_code == 200
    # The watchlist is stored per browser owner; the pin is observable via the API.
    assert client.get("/api/watchlist").json()["netuids"] == [12]
