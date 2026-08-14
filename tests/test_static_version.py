"""Regression coverage for homepage asset cache busting."""

from __future__ import annotations

import os
from pathlib import Path

from internal.static_version import _ASSET_ROOT, _ASSETS, STATIC_V


def test_static_version_covers_all_shipped_homepage_assets():
    static_root = os.path.dirname(_ASSET_ROOT)
    missing = [
        f"{directory}/{name}"
        for directory, name in _ASSETS
        if not os.path.isfile(os.path.join(static_root, directory, name))
    ]

    assert not missing
    assert len(_ASSETS) >= 30
    assert len(STATIC_V) == 8


def test_deferred_home_scripts_use_static_version():
    for template in (
        "templates/partials/mindmap_graph.html",
        "templates/partials/premium/dev_pulse.html",
    ):
        source = Path(template).read_text(encoding="utf-8")
        assert "src=\"/static/js/" in source
        assert "?v={{ static_v }}" in source
