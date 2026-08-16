"""Sealed Listening Post concept preview — hydrate off, 390px, not live pulse."""

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_listening_post_preview_is_sealed_and_has_four_decks():
    r = client.get("/preview/listening-post")
    assert r.status_code == 200
    html = r.text
    assert "dataset.hydrate = '0'" in html
    assert "max-width: 390px" in html
    assert "Listening Post" in html
    assert 'class="lp-station" data-deck="comms"' in html
    assert 'data-deck="crew"' in html
    assert 'data-deck="traffic"' in html
    assert 'data-deck="locker"' in html
    assert "No radio this watch" in html
    assert "Planet Subnet Summers" in html
    assert "message-intel-feed" not in html
    assert "message_intel_feed" not in html


def test_listening_post_preview_traffic_query():
    r = client.get("/preview/listening-post?deck=traffic")
    assert r.status_code == 200
    assert 'class="lp-station" data-deck="traffic"' in r.text
    assert "chatter weather" in r.text
