"""Cache-bust token for static asset links (`?v=...`).

Computed once at import from the mtimes of the shipped stylesheets and
homepage hydration scripts, so every deploy that touches dashboard rendering
gets a fresh token and browsers revalidate. Falls back to a fixed string when
the files are unreadable (tests, partial checkouts).
"""

from __future__ import annotations

import hashlib
import os

_ASSET_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "css"
)
_ASSETS = (
    ("css", "base.css"),
    ("css", "ui.css"),
    ("js", "cockpit_hydrate.js"),
    ("js", "message_intel_feed.js"),
    ("js", "home_live_refresh.js"),
)


def _token() -> str:
    parts = []
    for directory, name in _ASSETS:
        try:
            parts.append(str(os.stat(os.path.join(os.path.dirname(_ASSET_ROOT), directory, name)).st_mtime_ns))
        except OSError:
            continue
    if not parts:
        return "1"
    return hashlib.md5(":".join(parts).encode(), usedforsecurity=False).hexdigest()[:8]


STATIC_V = _token()
