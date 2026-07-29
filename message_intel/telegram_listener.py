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
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH")
TELEGRAM_PHONE = os.environ.get("TELEGRAM_PHONE")
TELEGRAM_GROUP = os.environ.get("TELEGRAM_GROUP", "officialsubnetsummer")
TELEGRAM_GROUP_ID = os.environ.get("TELEGRAM_GROUP_ID", "").strip()
# Canonical public link username (Telegram is case-insensitive; Telethon cache is not).
TELEGRAM_GROUP_USERNAME = "officialsubnetsummer"
try:
    TELEGRAM_BACKFILL_LIMIT = max(0, int(os.environ.get("TELEGRAM_BACKFILL_LIMIT", "100") or "100"))
except ValueError:
    TELEGRAM_BACKFILL_LIMIT = 100
try:
    TELEGRAM_BACKFILL_STALE_LIMIT = max(
        1, int(os.environ.get("TELEGRAM_BACKFILL_STALE_LIMIT", "500") or "500")
    )
except ValueError:
    TELEGRAM_BACKFILL_STALE_LIMIT = 500
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
        session: Any = None,
        forward_to_ingest: bool = True,
    ):
        self.api_id = int(api_id or TELEGRAM_API_ID or 0)
        self.api_hash = api_hash or TELEGRAM_API_HASH or ""
        self.phone = phone or TELEGRAM_PHONE or ""
        self.group = group or TELEGRAM_GROUP
        self.ingest_url = ingest_url or INGEST_URL
        self.on_message = on_message
        self.forward_to_ingest = forward_to_ingest
        self.session_name = session if session is not None else session_name
        self._client: Optional[Any] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.group_title: Optional[str] = None
        self.group_connected: bool = False
        self._monitor_entity: Optional[Any] = None
        self.telegram_user_label: Optional[str] = None
        self.entity_resolve_error: Optional[str] = None
        self.entity_resolve_attempts: list[str] = []

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
            self._running = False
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
                me = await self._connect_telegram()
                label = getattr(me, "username", None) or getattr(me, "id", "?")
                self.telegram_user_label = str(label)
                logger.info("Connected to Telegram as %s", me)

                # Resolve the group entity (username can fail when session cache is cold)
                try:
                    entity, via = await self._resolve_monitor_entity()
                    title = getattr(entity, "title", None) or str(self.group)
                    self.group_title = title
                    self.group_connected = True
                    self.entity_resolve_error = None
                    self._monitor_entity = entity
                    logger.info("Monitoring group: %s (via %s)", title, via)
                except Exception as e:
                    self.group_connected = False
                    self.group_title = None
                    self._monitor_entity = None
                    self.entity_resolve_error = str(e)
                    logger.error(
                        "Could not find group '%s' (attempts=%s): %s",
                        self.group,
                        self.entity_resolve_attempts[-8:],
                        e,
                    )
                    await asyncio.sleep(30)
                    continue

                # Register handler first — gap backfill async so live ingest isn't blocked
                @self._client.on(events.NewMessage(chats=entity))
                async def handler(event) -> None:  # noqa: F811
                    await self._handle_event(event)

                asyncio.create_task(self._backfill_on_connect(entity))

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

    async def _connect_telegram(self) -> Any:
        """Connect without blocking on interactive login when StringSession is set."""
        from telethon.sessions import StringSession

        uses_string = isinstance(self.session_name, StringSession) or bool(
            os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
        )
        if uses_string:
            await self._client.connect()
            if not await self._client.is_user_authorized():
                raise RuntimeError(
                    "TELEGRAM_SESSION_STRING unauthorized — re-bootstrap with "
                    "scripts/bootstrap_telegram_session.py"
                )
        elif self.phone:
            await self._client.start(phone=self.phone)
        else:
            await self._client.connect()
            if not await self._client.is_user_authorized():
                raise RuntimeError(
                    "Telegram session unauthorized — set TELEGRAM_SESSION_STRING or TELEGRAM_PHONE"
                )
        return await self._client.get_me()

    def _entity_lookup_keys(self) -> list[Any]:
        """Keys for get_entity — DB peer id first, then canonical lowercase username."""
        keys: list[Any] = []
        seen: set[str] = set()

        def add(key: Any) -> None:
            token = str(key)
            if token in seen:
                return
            seen.add(token)
            keys.append(key)

        try:
            from internal.message_intel.store import last_telegram_group_id

            gid = last_telegram_group_id()
            if gid is not None:
                add(gid)
        except Exception:
            pass

        canonical = TELEGRAM_GROUP_USERNAME
        add(canonical)
        add(f"@{canonical}")
        add(f"https://t.me/{canonical}")

        raw_id = (os.environ.get("TELEGRAM_GROUP_ID") or TELEGRAM_GROUP_ID or "").strip()
        if raw_id:
            try:
                add(int(raw_id))
            except ValueError:
                add(raw_id)

        group = (self.group or "").strip()
        if group:
            bare = group.lstrip("@")
            add(bare)
            add(f"@{bare}")
            add(f"https://t.me/{bare.lower()}")
            if bare.lower() != bare:
                add(bare.lower())
                add(f"@{bare.lower()}")
        return keys

    async def _resolve_via_username(self, username: str) -> tuple[Any, str]:
        from telethon.tl.functions.contacts import ResolveUsernameRequest

        bare = username.lstrip("@").lower()
        result = await self._client(ResolveUsernameRequest(username=bare))
        peer = getattr(result, "peer", None)
        if peer is None:
            raise ValueError(f"ResolveUsername returned no peer for {bare!r}")
        entity = await self._client.get_entity(peer)
        return entity, f"ResolveUsername({bare})"

    async def _resolve_monitor_entity(self) -> tuple[Any, str]:
        self.entity_resolve_attempts = []
        errors: list[str] = []

        for key in self._entity_lookup_keys():
            self.entity_resolve_attempts.append(f"get_entity({key})")
            try:
                entity = await self._client.get_entity(key)
                return entity, f"get_entity({key})"
            except Exception as exc:
                errors.append(f"{key}: {type(exc).__name__}: {exc}")
                logger.warning("Telegram get_entity(%s) failed: %s", key, exc)

        self.entity_resolve_attempts.append(f"ResolveUsername({TELEGRAM_GROUP_USERNAME})")
        try:
            return await self._resolve_via_username(TELEGRAM_GROUP_USERNAME)
        except Exception as exc:
            errors.append(f"ResolveUsername: {type(exc).__name__}: {exc}")
            logger.warning("Telegram ResolveUsername failed: %s", exc)

        want = (self.group or "").strip().lower().lstrip("@")
        aliases = {
            want,
            TELEGRAM_GROUP_USERNAME,
            "subnet summer",
            "subnet summers",
        }
        self.entity_resolve_attempts.append("iter_dialogs(500)")
        async for dialog in self._client.iter_dialogs(limit=500):
            ent = dialog.entity
            username = (getattr(ent, "username", "") or "").lower()
            title = (getattr(ent, "title", "") or "").lower()
            if username in aliases or title in aliases or title.startswith("subnet summer"):
                return ent, f"dialog({username or title})"

        detail = "; ".join(errors[-6:]) if errors else "no attempts logged"
        raise ValueError(f"no Telegram entity for {self.group!r} — {detail}")

    async def _forum_backfill_targets(self, entity: Any) -> list[Optional[int]]:
        """Forum supergroups need per-topic reply_to — main iter_messages misses topic threads."""
        targets: list[Optional[int]] = [None]
        if not getattr(entity, "forum", False):
            return targets
        try:
            from telethon.tl.functions.messages import GetForumTopicsRequest

            offset_topic = 0
            while True:
                result = await self._client(
                    GetForumTopicsRequest(
                        peer=entity,
                        q=None,
                        offset_date=None,
                        offset_id=0,
                        offset_topic=offset_topic,
                        limit=50,
                    )
                )
                topics = getattr(result, "topics", None) or []
                for topic in topics:
                    tid = getattr(topic, "id", None)
                    if tid is not None:
                        targets.append(int(tid))
                if len(topics) < 50:
                    break
                offset_topic = int(topics[-1].id)
            logger.info("forum backfill targets=%s topics=%s", len(targets), targets[1:])
        except Exception as exc:
            logger.warning("forum topics lookup failed (general stream only): %s", exc)
        return targets

    async def _backfill_gap(self, entity: Any, limit: int, min_id: Optional[int]) -> None:
        targets = await self._forum_backfill_targets(entity)
        per_target = max(50, limit // max(1, len(targets)))
        for reply_to in targets:
            await self._backfill_recent(
                entity,
                per_target,
                min_id=min_id,
                reply_to=reply_to,
            )

    async def _backfill_on_connect(self, entity: Any) -> None:
        """Gap-aware backfill — min_id skips already-ingested rows (dedup alone is not enough)."""
        try:
            from internal.message_intel.store import last_telegram_external_id, live_stats

            last_ext = last_telegram_external_id()
            stats = live_stats()
            age = stats.get("last_message_age_seconds")
            try:
                stale_threshold = float(os.environ.get("TELEGRAM_FEED_STALE_SECONDS", "7200"))
            except ValueError:
                stale_threshold = 7200.0
            stale = age is not None and float(age) > stale_threshold
            if stale and last_ext:
                limit = TELEGRAM_BACKFILL_STALE_LIMIT
            elif TELEGRAM_BACKFILL_LIMIT > 0:
                limit = TELEGRAM_BACKFILL_LIMIT
            else:
                return
            await self._backfill_gap(entity, limit, last_ext)
        except Exception as exc:
            logger.warning("Telegram connect backfill failed: %s", exc)

    async def _backfill_recent(
        self,
        entity: Any,
        limit: int,
        min_id: Optional[int] = None,
        reply_to: Optional[int] = None,
    ) -> None:
        """Ingest Telegram history — skip msg.id <= min_id client-side (forum-safe)."""
        new_count = 0
        deduped = 0
        skipped = 0
        skipped_old = 0
        try:
            kw: Dict[str, Any] = {"limit": limit}
            if reply_to is not None:
                kw["reply_to"] = reply_to
            async for msg in self._client.iter_messages(entity, **kw):
                if min_id is not None and min_id > 0 and int(msg.id) <= min_id:
                    skipped_old += 1
                    continue
                sender = await msg.get_sender()
                normalized = self._normalize_message(msg, sender, msg.chat_id)
                if normalized is None:
                    skipped += 1
                    continue
                if self.on_message:
                    from internal.message_intel.engine import ingest_message

                    result = ingest_message(normalized, snapshot_price=False)
                    if result.get("deduped"):
                        deduped += 1
                    else:
                        new_count += 1
                elif self.forward_to_ingest:
                    await self._forward_to_ingest(normalized)
                    new_count += 1
            logger.info(
                "Telegram backfill reply_to=%s min_id=%s limit=%s new=%s deduped=%s skipped=%s skipped_old=%s",
                reply_to,
                min_id,
                limit,
                new_count,
                deduped,
                skipped,
                skipped_old,
            )
        except Exception as exc:
            logger.warning("Telegram backfill failed: %s", exc)

    def _message_timestamp(self, msg: Any) -> str:
        dt = getattr(msg, "date", None)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        return datetime.now(timezone.utc).isoformat()

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
            "timestamp": self._message_timestamp(msg),
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

    def trigger_backfill(self, limit: Optional[int] = None, min_id: Optional[int] = None) -> bool:
        """Re-pull Telegram history newer than min_id (gap recovery after disconnect)."""
        if not self._running or not self._loop or not self._monitor_entity or not self._client:
            return False
        from internal.message_intel.store import last_telegram_external_id, live_stats

        last_ext = min_id if min_id is not None else last_telegram_external_id()
        stats = live_stats()
        age = stats.get("last_message_age_seconds")
        try:
            stale_threshold = float(os.environ.get("TELEGRAM_FEED_STALE_SECONDS", "7200"))
        except ValueError:
            stale_threshold = 7200.0
        stale = age is not None and float(age) > stale_threshold
        if limit is not None:
            lim = limit
        elif stale:
            lim = TELEGRAM_BACKFILL_STALE_LIMIT
        else:
            lim = TELEGRAM_BACKFILL_LIMIT
        if lim <= 0:
            return False

        async def _do() -> None:
            await self._backfill_gap(self._monitor_entity, lim, last_ext)

        try:
            fut = asyncio.run_coroutine_threadsafe(_do(), self._loop)
            fut.result(timeout=180)
            return True
        except Exception as exc:
            logger.warning("Telegram backfill trigger failed: %s", exc)
            return False

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