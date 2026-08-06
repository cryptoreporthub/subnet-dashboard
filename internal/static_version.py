"""Cache-bust token for static asset links (`?v=...`).

Computed once at import from the mtimes of the shipped stylesheets, so every
deploy that touches CSS gets a fresh token and browsers revalidate. Falls back
to a fixed string when the files are unreadable (tests, partial checkouts).
"""

from __future__ import annotations

import hashlib
import os

_CSS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "css"
)


def _token() -> str:
    parts = []
    for name in ("base.css", "ui.css"):
        try:
            parts.append(str(os.stat(os.path.join(_CSS_DIR, name)).st_mtime_ns))
        except OSError:
            continue
    if not parts:
        return "1"
    return hashlib.md5(":".join(parts).encode()).hexdigest()[:8]


STATIC_V = _token()
