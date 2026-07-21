"""Load shed middleware — health bypass under request pressure."""

from internal.load_shed import LoadShedMiddleware, bypass_path


def test_bypass_paths():
    assert bypass_path("/health")
    assert bypass_path("/api/health")
    assert bypass_path("/static/js/app.js")
    assert bypass_path("/api/letter/brain")
    assert bypass_path("/api/story-strip")
    assert bypass_path("/api/data-freshness")
    assert bypass_path("/")  # shell must never 503 into a blank phone screen
    assert not bypass_path("/api/top-picks")


def test_load_shed_middleware_class():
    assert LoadShedMiddleware is not None
