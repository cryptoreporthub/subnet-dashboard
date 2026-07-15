#!/usr/bin/env python3
"""One-time Telethon session bootstrap for message-intel (C1).

Run locally with API creds + phone; writes data/telegram_listener.session
for copy to the Fly volume (or set TELEGRAM_SESSION_PATH).

  TELEGRAM_API_ID=... TELEGRAM_API_HASH=... TELEGRAM_PHONE='+1...' \\
    python scripts/bootstrap_telegram_session.py
"""
from __future__ import annotations

import asyncio
import os
import sys


async def _main() -> None:
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    phone = os.environ.get("TELEGRAM_PHONE", "").strip()
    session = os.environ.get("TELEGRAM_SESSION_PATH", "data/telegram_listener").strip()
    if not api_id or not api_hash or not phone:
        print(
            "Required: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        from telethon import TelegramClient
    except ImportError:
        print("Install telethon: pip install 'telethon>=1.33.0'", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(session) or ".", exist_ok=True)
    client = TelegramClient(session, int(api_id), api_hash)
    await client.start(phone=phone)
    me = await client.get_me()
    label = getattr(me, "username", None) or getattr(me, "id", "?")
    print(f"OK — session saved to {session}.session (account: {label})")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(_main())
