"""One-shot Telegram entity resolve probe — run on Fly worker via machine exec."""
from __future__ import annotations

import asyncio
import json
import os


async def _main() -> None:
    from internal.message_intel.session import telegram_session_arg
    from message_intel.telegram_listener import TelegramListener, TELEGRAM_GROUP_USERNAME
    from telethon import TelegramClient

    listener = TelegramListener(forward_to_ingest=False)
    listener._client = TelegramClient(
        telegram_session_arg(),
        listener.api_id,
        listener.api_hash,
    )
    out: dict = {
        "TELEGRAM_GROUP": os.environ.get("TELEGRAM_GROUP"),
        "TELEGRAM_GROUP_ID": os.environ.get("TELEGRAM_GROUP_ID"),
        "canonical_username": TELEGRAM_GROUP_USERNAME,
        "lookup_keys": listener._entity_lookup_keys(),
    }
    try:
        me = await listener._connect_telegram()
        out["telegram_user"] = getattr(me, "username", None) or str(getattr(me, "id", "?"))
        entity, via = await listener._resolve_monitor_entity()
        out["ok"] = True
        out["via"] = via
        out["title"] = getattr(entity, "title", None)
        out["entity_id"] = getattr(entity, "id", None)
        out["forum"] = bool(getattr(entity, "forum", False))
    except Exception as exc:
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["attempts"] = listener.entity_resolve_attempts
    finally:
        if listener._client:
            await listener._client.disconnect()
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(_main())
