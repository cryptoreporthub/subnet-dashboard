"""Upstream source availability (credentials from env only; no hardcoded secrets)."""

from __future__ import annotations

import os
from typing import Any, Dict


def source_status() -> Dict[str, Any]:
    """Report which social ingest sources are configured vs unreachable."""
    from internal.message_intel.session import has_telegram_session

    telegram = {
        "configured": bool(os.environ.get("TELEGRAM_API_ID") and os.environ.get("TELEGRAM_API_HASH")),
        "session": has_telegram_session(),
        "channels": os.environ.get("TELEGRAM_CHANNELS", ""),
        "group": os.environ.get("TELEGRAM_GROUP", "officialsubnetsummer"),
    }
    discord = {
        "configured": bool(os.environ.get("DISCORD_BOT_TOKEN")),
        "guilds": os.environ.get("DISCORD_GUILD_IDS", ""),
    }
    return {
        "telegram": telegram,
        "discord": discord,
        "ingest_url": os.environ.get("INGEST_URL", ""),
    }
