# Phase L Slice 3 — WebSocket design (Grok-fast-xhigh audit → Composer spec)

**Date:** 2026-07-12  
**Model:** grok-4.5-fast-xhigh (read-only audit) → Composer build  
**Audit input:** `cursor-agents-communication/phase-l-pr113-audit.md` (#113 vs #115)  
**Stack:** FastAPI + Uvicorn/Gunicorn (`server:app`) — native `WebSocket` support, no Flask

## Feasibility verdict: ✅ PROCEED

FastAPI exposes `/ws/signals` without a separate ASGI process. Gunicorn with `uvicorn.workers.UvicornWorker` (existing Fly `web` process) supports WebSockets. No blocker.

## Connection lifecycle

| Phase | Behavior |
|-------|----------|
| **Connect** | `await websocket.accept()` → register in `SignalBroadcastHub` → send `connected` snapshot (`signals` + `alerts`) |
| **Heartbeat** | Client sends `ping` → server replies `pong` (or coalesced `signals` on `refresh`) |
| **Refresh** | Client sends `refresh` → run `generate_signals(persist=True)` + system alert checks → unicast `signals` to requester; hub `broadcast` to all on pipeline refresh |
| **Disconnect** | `WebSocketDisconnect` or send failure → remove from hub set |
| **Reconnect** | Client opens new socket; server sends fresh `connected` snapshot (stateless per connection) |

No server-side session tokens. Reconnect is idempotent.

## Fan-out strategy

- **Global broadcast hub** (`internal/signals/ws_hub.py`) — single room, all subscribers receive `signals` and `alerts` events.
- **Per-client unicast** on explicit `refresh` ping for the requesting socket only (lower latency for single client).
- Dead sockets pruned on `send_text` failure.

Rationale: dashboard is one operator view; per-netuid rooms add complexity without current UI need.

## Message schema

```json
{ "type": "<event>", "data": { ... } }
```

| `type` | `data` shape | Direction |
|--------|--------------|-----------|
| `connected` | `{ "signals": [...], "alerts": [...] }` | server → client (on connect) |
| `signals` | `{ "signals": [...], "meta": {...} }` | server → client |
| `alerts` | `{ "alerts": [...] }` | server → broadcast |
| `pong` | `{}` | server → client (heartbeat ack) |

## Integration points

- **Routes:** `internal/signals/routes.py` — `@signals_router.websocket("/ws/signals")`
- **Trigger:** `_refresh_and_broadcast()` called from `GET /api/signals?refresh=true` and WS `refresh`
- **No grading/resolver changes** — consumes `generate_signals()` output only

## Composer implementation checklist

- [x] `SignalBroadcastHub` with connect/disconnect/broadcast
- [x] `/ws/signals` endpoint with `connected` snapshot
- [x] `ping` / `refresh` / `pong` handling
- [x] Tests: lifecycle, broadcast prune, refresh delivery

## Out of scope (document, do not force)

- Sticky sessions across multiple Gunicorn workers (each worker has its own hub; acceptable for MVP)
- WSS termination (Fly proxy handles TLS)
- Telegram/Discord push from WS (use `POST /api/alerts/subscribe` webhooks instead)
