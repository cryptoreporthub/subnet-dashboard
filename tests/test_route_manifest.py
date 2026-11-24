"""The app must keep serving every route and mount in the stored manifest.

``test_no_route_or_mount_was_lost`` is the permanent contract. A lost route breaks a caller.
``test_no_unlisted_route_added`` and the middleware order only hold while the server.py refactor
runs (docs/server-refactor-plan.md). Delete both in R12, when new routes become ordinary changes.
"""

import json
from pathlib import Path

from scripts.route_manifest import build_manifest

STORED = json.loads((Path(__file__).parent / "fixtures" / "route_manifest.json").read_text())


def _pairs(manifest):
    return {tuple(route) for route in manifest["routes"]}


def test_no_route_or_mount_was_lost():
    current = build_manifest()
    assert sorted(_pairs(STORED) - _pairs(current)) == []
    assert set(STORED["mounts"]) <= set(current["mounts"])


def test_no_unlisted_route_added():
    assert sorted(_pairs(build_manifest()) - _pairs(STORED)) == []


def test_middleware_order_is_unchanged():
    assert build_manifest()["middleware"] == STORED["middleware"]
