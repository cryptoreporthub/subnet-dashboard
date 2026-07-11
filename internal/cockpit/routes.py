"""Optional GET /api/cockpit/sections — mount via learning_router or server (Agent B)."""

from __future__ import annotations

from fastapi import APIRouter

from internal.cockpit.sections import get_cockpit_sections

cockpit_router = APIRouter(tags=["cockpit"])


@cockpit_router.get("/api/cockpit/sections")
async def api_cockpit_sections():
    """Return all 12 Premium Cockpit sections with live summaries."""
    return get_cockpit_sections()
