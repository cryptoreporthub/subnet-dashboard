"""The app must keep serving every route, mount, and middleware in the stored manifest."""

import json
from pathlib import Path

from scripts.route_manifest import build_manifest

STORED = json.loads((Path(__file__).parent / "fixtures" / "route_manifest.json").read_text())


def test_no_route_or_mount_was_lost_or_added():
    current = build_manifest()
    stored_routes = {tuple(r) for r in STORED["routes"]}
    current_routes = {tuple(r) for r in current["routes"]}
    assert sorted(stored_routes - current_routes) == [], "routes removed"
    assert sorted(current_routes - stored_routes) == [], "routes added without updating the manifest"
    assert current["mounts"] == STORED["mounts"]


def test_middleware_order_is_unchanged():
    assert build_manifest()["middleware"] == STORED["middleware"]
