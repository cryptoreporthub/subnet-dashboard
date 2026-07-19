"""K3 HOLD preview route."""

from fastapi.testclient import TestClient

from server import app


def test_preview_k3_hold_renders_full_dossier():
    with TestClient(app) as client:
        resp = client.get("/preview/k3-hold")
        html = resp.text
    assert resp.status_code == 200
    assert "K3 preview" in html
    assert "k3-horizon-chips" in html
    assert "k3-candidate-gate" in html
    assert "audit gate not cleared" in html
    assert 'id="k3-orb-score"' in html
    assert "Deliberation" in html
    assert "k3-considered-card" in html
    assert 'dataset.hydrate = \'0\'' in html or "dataset.hydrate = '0'" in html
