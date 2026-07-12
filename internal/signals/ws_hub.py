"""WebSocket broadcast hub for live signal + alert updates."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class SignalBroadcastHub:
    """Track connected clients and push JSON events."""

    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        message = json.dumps({"type": event_type, "data": payload})
        dead: List[WebSocket] = []
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)


_hub: SignalBroadcastHub | None = None


def get_signal_hub() -> SignalBroadcastHub:
    global _hub
    if _hub is None:
        _hub = SignalBroadcastHub()
    return _hub
