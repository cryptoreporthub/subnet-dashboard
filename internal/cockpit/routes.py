"""Optional read API for cockpit sections (mount via guarded include_router)."""

from __future__ import annotations

from fastapi import APIRouter

from internal.cockpit.sections import get_cockpit_section, get_cockpit_sections

cockpit_router = APIRouter(tags=["cockpit"])


@cockpit_router.get("/api/cockpit/sections")
async def api_cockpit_sections():
    """All 12 Premium Cockpit section cards."""
    return get_cockpit_sections()


@cockpit_router.get("/api/cockpit/sections/{section_id}")
async def api_cockpit_section(section_id: str):
    """Single cockpit section card."""
    return get_cockpit_section(section_id)
