"""Load shed middleware — health bypass under request pressure."""

from internal.load_shed import LoadShedMiddleware, bypass_path


def test_bypass_paths():
    assert bypass_path("/health")
    assert bypass_path("/api/health")
    assert bypass_path("/version")
    assert bypass_path("/api/ops/live")
    assert bypass_path("/static/js/app.js")
    assert bypass_path("/api/letter/brain")
    assert bypass_path("/api/data-freshness")
    assert bypass_path("/api/judges/28")
    assert bypass_path("/")  # shell must never 503 into a blank phone screen
    assert not bypass_path("/api/top-picks")
    assert not bypass_path("/api/judges")  # all-subnet scoring stays shedable


def test_offloaded_hydrate_paths_are_not_light():
    """Cut A+B: blocking hydrate handlers no longer bypass load shed."""
    for path in (
        "/api/mindmap/trail",
        "/api/story-strip",
        "/api/portfolio/status",
        "/api/subnet-integrations",
        "/api/ops/evidence",
    ):
        assert not bypass_path(path), f"{path} should be shedable, not light/bypass"


def test_ops_live_stays_bypass_while_evidence_is_shedable():
    assert bypass_path("/api/ops/live")
    assert not bypass_path("/api/ops/evidence")


def test_load_shed_middleware_class():
    assert LoadShedMiddleware is not None
