"""Plain-language summary for the message-intel panel (Phase C)."""

from __future__ import annotations

from typing import Any, Dict, List

from internal.message_intel.sources import source_status
from internal.message_intel.store import live_stats


def _sentences(parts: List[str]) -> Dict[str, Any]:
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return {"text": text, "sentences": [p.strip() for p in parts if p and p.strip()]}


def summarize_message_intel() -> Dict[str, Any]:
    """Return 3–4 sentences from live SQLite + Soul-Map message-intel state."""
    stats = live_stats()
    sources = source_status()
    parts: List[str] = []

    if not stats.get("ok"):
        parts.append(
            f"Message-intel store is unavailable ({stats.get('error', 'unknown error')}); "
            "ingest endpoints will report the upstream failure instead of faking chatter."
        )
        parts.append(
            "Configure TELEGRAM_API_ID/TELEGRAM_API_HASH or DISCORD_BOT_TOKEN to enable "
            "live social listeners; until then POST /api/message-intel/ingest accepts pushed messages."
        )
        return _sentences(parts)

    total = int(stats.get("total_messages") or 0)
    high = int(stats.get("high_conviction_count") or 0)
    channels = stats.get("channels") or []

    if total == 0:
        parts.append(
            "No social messages are persisted yet — the pipeline is wired but waiting for "
            "telegram/discord ingest or manual POST /api/message-intel/ingest payloads."
        )
    else:
        parts.append(
            f"Message-intel holds {total} analyzed messages with {high} high-conviction verdicts "
            f"stored in the SQLite pipeline."
        )
        if channels:
            top = channels[0]
            parts.append(
                f"The busiest source is {top.get('source')} ({top.get('count')} messages); "
                "NLP + jury scoring runs on every ingest and updates Soul-Map dispositions."
            )
        recent = stats.get("recent") or []
        if recent:
            row = recent[0]
            parts.append(
                f"Latest signal from {row.get('group_name') or row.get('source')}: "
                f"{row.get('verdict') or 'pending'} at {row.get('conviction') or 0:.0f}% conviction."
            )

    configured = []
    if sources["telegram"]["configured"]:
        configured.append("Telegram")
    if sources["discord"]["configured"]:
        configured.append("Discord")
    if configured:
        parts.append(f"Live listeners configured for {', '.join(configured)}.")
    else:
        parts.append(
            "No live listener credentials are set; social feeds degrade gracefully and "
            "only manual/API ingest populates the store."
        )

    return _sentences(parts[:4])
