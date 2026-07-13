"""
Telegram Listener — monitors Telegram groups for new messages.

Uses Telethon with session persistence to connect and listen to
the configured group, forwarding normalized messages to a callback
or the FastAPI ingest endpoint.
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH")
TELEGRAM_PHONE = os.environ.get("TELEGRAM_PHONE")
TELEGRAM_GROUP = os.environ.get("TELEGRAM_GROUP", "OfficialSubnetSummer")
INGEST_URL = os.environ.get(
    "INGEST_URL", "http://localhost:8080/api/message-intel/ingest"
)

# Import telethon lazily so the package can be imported without it
try:
    from telethon import TelegramClient, events
    from telethon.errors import (
        FloodWaitError,
        RPCError,
    )
    HAS_TELETHON = True
except ImportError:
    HAS_TELETHON = False


class TelegramListener:
    """
    Background listener that monitors a Telegram group for new messages.

    Runs as an asyncio task in a daemon thread, forwarding normalized
    messages to the Flask ingest endpoint.
    """

    def __init__(
        self,
        api_id: Optional[str] = None,
        api_hash: Optional[str] = None,
        phone: Optional[str] = None,
        group: Optional[str] = None,
        ingest_url: Optional[str] = None,
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
        session_name: str = "telegram_listener",
        forward_to_ingest: bool = True,
    ):
        self.api_id = int(api_id or TELEGRAM_API_ID or 0)
        self.api_hash = api_hash or TELEGRAM_API_HASH or ""
        self.phone = phone or TELEGRAM_PHONE or ""
        self.group = group or TELEGRAM_GROUP
        self.ingest_url = ingest_url or INGEST_URL
        self.on_message = on_message
        self.forward_to_ingest = forward_to_ingest
        self.session_name = session_name
        self._client: Optional[Any] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self) -> bool:
        """
        Start the listener in a background daemon thread.

        Returns:
            True if started successfully, False if telethon is not installed.
        """
        if not HAS_TELETHON:
            logger.warning(
                "Telethon not installed. Install with: pip install telethon>=1.33.0"
            )
            return False

        if self._running:
            logger.info("Listener is already running")
            return True

        if not self.api_id or not self.api_hash:
            logger.warning(
                "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set"
            )
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._run_async_loop,
            daemon=True,
            name="telegram-listener",
        )
        self._thread.start()
        logger.info("Telegram listener started in background thread")
        return True

    def _run_async_loop(self) -> None:
        """Run the asyncio event loop in the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_client())
        except Exception as e:
            logger.error("Telegram listener error: %s", e)
        finally:
            self._loop.close()

    async def _run_client(self) -> None:
        """
        Connect to Telegram and listen for new messages in the group.

        Handles reconnection with exponential backoff.
        """
        self._client = TelegramClient(
            self.session_name,
            self.api_id,
            self.api_hash,
        )

        retry_delay = 1
        max_retry_delay = 300  # 5 minutes

        while self._running:
            try:
                await self._client.start(phone=self.phone)
                logger.info(
                    "Connected to Telegram as %s", await self._client.get_me()
                )

                # Resolve the group entity
                try:
                    entity = await self._client.get_entity(self.group)
                    logger.info("Monitoring group: %s", entity.title)
                except ValueError as e:
                    logger.error(
                        "Could not find group '%s': %s", self.group, e
                    )
                    await asyncio.sleep(30)
                    continue

                # Register the message handler
                @self._client.on(events.NewMessage(chats=entity))
                async def handler(event) -> None:  # noqa: F811
                    await self._handle_event(event)

                # Reset retry delay on successful connection
                retry_delay = 1

                # Keep running until stopped or disconnected
                await self._client.run_until_disconnected()

            except FloodWaitError as e:
                logger.warning(
                    "Rate limited. Waiting %d seconds...", e.seconds
                )
                await asyncio.sleep(e.seconds)
            except RPCError as e:
                logger.warning("RPC error: %s. Retrying in %ds...", e, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)
            except OSError as e:
                logger.warning(
                    "Connection error: %s. Retrying in %ds...", e, retry_delay
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)
            except Exception as e:
                logger.error(
                    "Unexpected error: %s. Retrying in %ds...", e, retry_delay
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def _handle_event(self, event) -> None:
        """Normalize a Telegram message event and forward it."""
        try:
            sender = await event.get_sender()
            msg = event.message

            normalized = self._normalize_message(msg, sender, event.chat_id)
            if normalized is None:
                return

            logger.debug(
                "Received message from %s: %.60s...",
                normalized.get("author_name", "unknown"),
                normalized.get("content", ""),
            )

            # Call local callback if set
            if self.on_message:
                self.on_message(normalized)

            # Forward to ingest endpoint when no in-process handler
            if self.forward_to_ingest and not self.on_message:
                await self._forward_to_ingest(normalized)

        except Exception as e:
            logger.error("Error handling message event: %s", e)

    def _normalize_message(
        self,
        msg: Any,
        sender: Any,
        chat_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Normalize a Telethon message into our standard format.

        Returns None for non-text messages (stickers, media, etc.).
        """
        content = msg.text or msg.message
        if not content or not content.strip():
            return None

        # Skip messages that are too short to analyze
        if len(content.strip()) < 3:
            return None

        normalized: Dict[str, Any] = {
            "source": "telegram",
            "group_id": str(chat_id),
            "group_name": self.group,
            "author_id": str(sender.id) if sender else None,
            "author_name": (
                getattr(sender, "first_name", None) or
                getattr(sender, "username", None) or
                "Unknown"
            ),
            "author_username": (
                f"@{sender.username}" if sender and getattr(sender, "username", None) else None
            ),
            "content": content.strip(),
            "timestamp": datetime.now().isoformat(),
            "message_id": str(msg.id),
        }

        # Capture engagement metrics when available
        metrics: Dict[str, Any] = {}
        if hasattr(msg, "views") and msg.views is not None:
            metrics["views"] = msg.views
        if hasattr(msg, "forwards") and msg.forwards is not None:
            metrics["forwards"] = msg.forwards
        if hasattr(msg, "reply_to") and msg.reply_to:
            metrics["replies"] = 1  # Indicates this is a reply

        # Reactions
        if hasattr(msg, "reactions") and msg.reactions:
            try:
                reactions = []
                for r in msg.reactions.results or []:
                    reactions.append({
                        "emoji": r.reaction.emoticon if hasattr(r.reaction, "emoticon") else str(r.reaction),
                        "count": r.count,
                    })
                metrics["reactions"] = reactions
            except Exception:
                pass

        if metrics:
            normalized["metrics"] = metrics

        return normalized

    async def _forward_to_ingest(self, normalized: Dict[str, Any]) -> None:
        """POST the normalized message to the Flask ingest endpoint."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.ingest_url,
                    json=normalized,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status not in (200, 201):
                        text = await resp.text()
                        logger.warning(
                            "Ingest returned %d: %s", resp.status, text[:200]
                        )
        except ImportError:
            # Fallback to urllib if aiohttp not available
            await self._forward_urllib(normalized)
        except Exception as e:
            logger.warning("Failed to forward message to ingest: %s", e)

    async def _forward_urllib(self, normalized: Dict[str, Any]) -> None:
        """Fallback forwarding using urllib."""
        try:
            import urllib.request

            data = json.dumps(normalized).encode()
            req = urllib.request.Request(
                self.ingest_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=5)
            )
        except Exception as e:
            logger.warning("Urllib forward failed: %s", e)

    def stop(self) -> None:
        """Stop the listener gracefully."""
        self._running = False
        if self._client and self._loop and not self._loop.is_closed():
            async def _disconnect():
                await self._client.disconnect()

            try:
                asyncio.run_coroutine_threadsafe(
                    _disconnect(), self._loop
                )
            except Exception:
                pass
        logger.info("Telegram listener stopped")