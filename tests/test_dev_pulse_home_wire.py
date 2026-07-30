"""Dev Pulse homepage wire."""

from pathlib import Path


def test_premium_cockpit_includes_dev_pulse():
    html = Path("templates/partials/premium_cockpit.html").read_text(encoding="utf-8")
    assert 'include "partials/premium/dev_pulse.html"' in html
    assert "section-dev-pulse" not in html  # id lives in partial, not inline
