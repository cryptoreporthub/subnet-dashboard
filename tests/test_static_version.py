"""Regression coverage for homepage asset cache busting."""

from __future__ import annotations

import os

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
