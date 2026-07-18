"""Load shed middleware — health bypass under request pressure."""

from internal.load_shed import LoadShedMiddleware, bypass_path


def test_bypass_paths():
    assert bypass_path("/health")
    assert bypass_path("/api/health")
    assert bypass_path("/static/js/app.js")
    assert not bypass_path("/")
    assert not bypass_path("/api/daily-pick")


def test_load_shed_middleware_class():
    assert LoadShedMiddleware is not None
