"""§21 L12 / §22 S22-3 — prediction time-capsule replay + OG share card."""

from internal.learning.prediction_capsule import (
    build_og_svg,
    build_share_card,
    capsule_share_urls,
    get_prediction_capsule,
)


def test_capsule_not_found():
    out = get_prediction_capsule("nonexistent-id-xyz")
    assert out["status"] == "not_found"


def test_capsule_and_share_card(tmp_path, monkeypatch):
    pred_path = tmp_path / "predictions.json"
    pred_path.write_text(
        """{
      "predictions": [],
      "resolved": [{
        "id": "pred_capsule_1",
        "netuid": 8,
        "name": "Taoshi",
        "statement": "Token up on delegation flow",
        "predicted_pct": 3.5,
        "actual_pct": 2.1,
        "correct": true,
        "outcome": "hit",
        "subnet_snapshot": {
          "staking_yield_apy": 12.0,
          "price_change_7d": -4.0,
          "yield_trap": true
        },
        "judge_scores_at_creation": {
          "oracle": {"confidence": 0.72},
          "echo": {"score": 0.65}
        }
      }],
      "stats": {}
    }"""
    )
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(pred_path))

    out = get_prediction_capsule("pred_capsule_1")
    assert out["status"] == "success"
    assert out["capsule"]["subnet_snapshot"]["yield_trap"] is True
    share = build_share_card(out["prediction"])
    assert "Taoshi" in share
    assert "yield trap" in share.lower() or "Yield trap" in share
    urls = capsule_share_urls("pred_capsule_1")
    assert urls["share_image_url"].endswith("/pred_capsule_1/og.svg")
    assert urls["share_page_url"] == "/share/call/pred_capsule_1"
    assert out["share_image_url"] == urls["share_image_url"]


def test_og_svg_contains_verdict_and_name():
    svg = build_og_svg(
        {
            "name": "Taoshi",
            "netuid": 8,
            "predicted_pct": 3.5,
            "actual_pct": 2.1,
            "correct": True,
            "statement": "Token up on delegation flow",
            "subnet_snapshot": {"yield_trap": True, "price_change_7d": -4.0},
        }
    )
    assert svg.startswith("<?xml")
    assert "Taoshi" in svg
    assert "HIT" in svg
    assert "yield trap" in svg
    assert "Expected +3.5%" in svg


def test_og_svg_route_and_share_page(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import server

    pred_path = tmp_path / "predictions.json"
    pred_path.write_text(
        """{
      "predictions": [],
      "resolved": [{
        "id": "pred_og_1",
        "netuid": 3,
        "name": "Gamma",
        "statement": "Momentum continuation",
        "predicted_pct": 2.0,
        "actual_pct": 1.5,
        "correct": true,
        "outcome": "hit"
      }],
      "stats": {}
    }"""
    )
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(pred_path))

    client = TestClient(server.app)
    og = client.get("/api/predictions/capsule/pred_og_1/og.svg")
    assert og.status_code == 200
    assert "image/svg+xml" in og.headers.get("content-type", "")
    assert "Gamma" in og.text
    assert "HIT" in og.text

    page = client.get("/share/call/pred_og_1")
    assert page.status_code == 200
    assert 'property="og:image"' in page.text
    assert "Gamma" in page.text

    missing = client.get("/api/predictions/capsule/missing-id/og.svg")
    assert missing.status_code == 200
    assert "image/svg+xml" in missing.headers.get("content-type", "")

    missing_page = client.get("/share/call/missing-id")
    assert missing_page.status_code == 200
