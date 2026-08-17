"""Cache-bust token for homepage static asset links (``?v=...``).

Computed once at import from the mtimes of the shipped stylesheets and all
homepage JavaScript, so a deploy that touches any below-fold hydrator also
causes browsers to revalidate it. Falls back to a fixed string when the files
are unreadable (tests, partial checkouts).
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
    ("css", "listener.css"),
    # Keep this list aligned with the homepage script includes and the
    # deferred scripts loaded by home_deferred.js. All of these share the
    # static_v token in templates, so one token must cover every hydrator.
    ("js", "conviction_tiers.js"),
    ("js", "empty_state.js"),
    ("js", "weighing_room.js"),
    ("js", "data_freshness.js"),
    ("js", "api_fetch.js"),
    ("js", "ops_readiness_badge.js"),
    ("js", "subnet_integrations.js"),
    ("js", "trust_banner_ui.js"),
    ("js", "market_drivers_ui.js"),
    ("js", "brain_letter.js"),
    ("js", "story_path_ui.js"),
    ("js", "paper_portfolio.js"),
    ("js", "weekly_letter.js"),
    ("js", "daily_recap.js"),
    ("js", "watchlist_alerts.js"),
    ("js", "letter_export.js"),
    ("js", "time_capsule.js"),
    ("js", "hour_watch_ui.js"),
    ("js", "pump_map.js"),
    ("js", "cockpit_hydrate.js"),
    ("js", "message_intel_feed.js"),
    ("js", "listener.js"),
    ("js", "home_live_refresh.js"),
    ("js", "living_focus.js"),
    ("js", "home_deferred.js"),
    ("js", "thumb_dock.js"),
    ("js", "mindmap_graph.js"),
    ("js", "dev_pulse.js"),
    ("js", "uplot_charts.js"),
    ("js", "premium_signals.js"),
    ("js", "subnet_grouping.js"),
    ("js", "premium_scanner.js"),
    ("js", "investigation_panel.js"),
    ("js", "premium_judges.js"),
    ("js", "subnet_report.js"),
    ("js", "social_sentiment.js"),
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
