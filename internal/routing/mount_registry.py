"""Single registry for APIRouter mounts on server:app.

Agents copy nearest `include_router` in server.py; this module is the one
supported mount list. CI imports it to prove every slice router loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

from fastapi import APIRouter


@dataclass(frozen=True)
class RouterMount:
    name: str
    loader: Callable[[], APIRouter]


def _load(name: str, import_path: str, attr: str) -> APIRouter:
    module = __import__(import_path, fromlist=[attr])
    router = getattr(module, attr)
    if not isinstance(router, APIRouter):
        raise TypeError(f"{import_path}.{attr} is not an APIRouter")
    return router


# Order matches server.py for minimal behavioral diff.
MOUNTS: List[RouterMount] = [
    RouterMount("whales", lambda: _load("whales", "internal.whales.routes", "whales_router")),
    RouterMount("watchlist", lambda: _load("watchlist", "internal.watchlist.routes", "watchlist_router")),
    RouterMount("portfolio", lambda: _load("portfolio", "internal.portfolio.routes", "portfolio_router")),
    RouterMount("letter", lambda: _load("letter", "internal.letter.routes", "letter_router")),
    RouterMount("council", lambda: _load("council", "internal.judges.council_routes", "council_router")),
    RouterMount("learning", lambda: _load("learning", "internal.learning.routes", "learning_router")),
    RouterMount("simivision", lambda: _load("simivision", "internal.simivision.routes", "simivision_router")),
    RouterMount("ruggers", lambda: _load("ruggers", "internal.ruggers.routes", "ruggers_router")),
    RouterMount("indicators", lambda: _load("indicators", "internal.indicators.routes", "indicators_router")),
    RouterMount("oracle", lambda: _load("oracle", "internal.oracle.routes", "oracle_router")),
    RouterMount("analytics", lambda: _load("analytics", "internal.analytics.routes", "analytics_router")),
    RouterMount("health", lambda: _load("health", "internal.health.routes", "health_router")),
    RouterMount("cockpit", lambda: _load("cockpit", "internal.cockpit", "cockpit_router")),
    RouterMount("store", lambda: _load("store", "internal.analytics.store_routes", "store_router")),
    RouterMount("mindmap_graph", lambda: _load("mindmap_graph", "internal.mindmap", "mindmap_graph_router")),
    RouterMount("signals", lambda: _load("signals", "internal.signals", "signals_router")),
    RouterMount("dev_radar", lambda: _load("dev_radar", "internal.dev_radar.routes", "dev_radar_router")),
    RouterMount(
        "investigation",
        lambda: _load("investigation", "internal.investigation", "investigation_router"),
    ),
    RouterMount("share", lambda: _load("share", "internal.share_pages.routes", "share_router")),
    RouterMount(
        "conviction_index",
        lambda: _load("conviction_index", "internal.conviction_index.routes", "conviction_index_router"),
    ),
]


def load_all() -> List[tuple[str, APIRouter]]:
    loaded = []
    for mount in MOUNTS:
        loaded.append((mount.name, mount.loader()))
    return loaded
