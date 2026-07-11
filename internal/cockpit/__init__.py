"""Premium Cockpit data layer (Phase E Agent A)."""

from internal.cockpit.sections import (
    COCKPIT_SECTION_IDS,
    SECTION_TITLES,
    get_cockpit_section,
    get_cockpit_sections,
)

__all__ = [
    "COCKPIT_SECTION_IDS",
    "SECTION_TITLES",
    "get_cockpit_section",
    "get_cockpit_sections",
]

try:
    from internal.cockpit.routes import cockpit_router
except ImportError:
    cockpit_router = None  # type: ignore[misc, assignment]

if cockpit_router is not None:
    __all__.append("cockpit_router")
