# Phase M — Social Live Ingestion (Grok design → Composer spec)

**Date:** 2026-07-13  
**Model:** grok-4.5-xhigh design pass → Composer build  
**Stack:** FastAPI + Uvicorn (`server:app`) — **not Flask/Gunicorn**  
**main:** `fbf0f27` (post-Phase L)

## Verdict: ✅ PROCEED

Substantial Phase C message-intel code already exists (`internal/message_intel/*`, `message_intel/telegram_listener.py`). Phase M wires the listener, dedup, public API alias, Jinja context, and optional Phase L alert hooks — no greenfield rewrite.

---

## 1. Ingestion architecture

### Telethon + FastAPI fit

| Approach | Verdict |
|----------|---------|
| Telethon inside Uvicorn process (daemon thread + asyncio loop) | ✅ **Recommended** — matches existing `TelegramListener` |
| Separate worker process | Optional later; not required for M |
| HTTP self-loopback only | ❌ Avoid on Fly single-process deploy |

`message_intel/telegram_listener.py` already runs Telethon in a **daemon thread** with its own asyncio loop, exponential backoff on `RPCError`/`OSError`, and `FloodWaitError` sleep. Wire it via `server.py` lifespan — same pattern as `resolver_scheduler`.

### Rate limits

- Honor `FloodWaitError.seconds` (already implemented).
- Exponential backoff 1s → 300s cap on RPC/connection errors (already implemented).
- Ingest path is **per-message NLP** — batch Soul-Map sync at end of batch only.
- ponytail ceiling: no global ingest queue; if volume exceeds ~10 msg/s, drop to `logger.warning` + skip (upgrade path: bounded `asyncio.Queue`).

### Dedup uniqueness

**Key:** `(source, group_id, external_message_id)` where `external_message_id` = Telegram `msg.id` (string).

Same message reposted across channels = **distinct rows** (different `group_id`). Same channel + same `message_id` = **one row** (return existing id, `deduped: true` in ingest response).

---

## 2. Data flow

```
Telegram (Telethon)
  → TelegramListener._normalize_message()
  → on_message callback (direct, no HTTP loopback)
  → engine.ingest_message()
       → SQLite data/message_intel.db (canonical store)
       → NLP + jury + Soul-Map sync (existing)
       → signals_bridge.emit_social_alert_if_needed()  [optional, Phase L consumer]
            → AlertEngine.create_alert() → data/alerts.json
  → cockpit _build_message_intel() reads live_stats() → live | empty | unavailable
  → GET /api/message-intel → list_messages()
  → Jinja message_intel context on GET /
```

### Existing files

| Path | Role |
|------|------|
| `message_intel/telegram_listener.py` | Telethon client, normalize, reconnect |
| `internal/message_intel/engine.py` | ingest, list, pipeline |
| `message_intel/models.py` | SQLite schema |
| `internal/message_intel/routes.py` | `/api/message-intel/*` |
| `internal/cockpit/sections.py` | `_build_message_intel()` |

### Phase L integration (consume, don't modify core)

Social alerts use **`AlertEngine.create_alert()`** with `alert_type: "social_intel"` and `dedupe_key: social:{source}:{group_id}:{message_id}`. Phase L rules engine (`correlation.py`) unchanged. WS hub receives alerts via existing broadcast on alert create (if refresh path runs).

**Dependency:** Phase L alerts API + `AlertEngine` must be on `main` (✅ merged PR #115).

---

## 3. Persistence

| Store | Format | Notes |
|-------|--------|-------|
| **`data/message_intel.db`** | SQLite (WAL) | **Canonical** — already in repo pattern |
| `data/message_intel.json` | Not used | Task mention superseded by existing SQLite; honest-empty API returns `[]` |

Volume: SQLite WAL handles hundreds/hour. Dashboard reads are **paginated** (`limit` default 20–50). No blocking on hot path.

Optional export JSON mirror deferred (YAGNI).

---

## 4. Cockpit integration

- `message_intel` cockpit card already calls `summarize_message_intel()` + `live_stats()`.
- Phase M makes card **live** when messages exist (ingest populates DB).
- New **`GET /api/message-intel`** — alias of list (empty `messages: []` when none).
- Jinja: `build_message_intel_context()` adds `message_intel` dict to `GET /` (templates unchanged this slice; Agent B or follow-up can render).

---

## 5. Failure modes

| Failure | Behavior |
|---------|----------|
| Telethon disconnect | Reconnect loop with backoff (existing) |
| Missing `TELEGRAM_API_ID`/`HASH` | Listener skipped; `source_status()` reports unconfigured; honest-empty |
| Expired session | Log error; listener retries; ingest API still accepts manual POST |
| No messages for hours | `total_messages: 0`; cockpit `status: empty` |
| NLP unavailable | `MessageIntelUnavailable`; ingest returns error, no fake rows |

---

## 6. Security

| Secret | Storage |
|--------|---------|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` | Fly secrets / `.env` (never committed) |
| Session file | `data/telegram_listener.session` on volume or `TELEGRAM_SESSION_PATH` |
| `MESSAGE_INTEL_LISTENER=off` | Disable auto-start (CI/tests) |

---

## Data flow diagram (text)

```
[Telegram API] --Telethon--> [TelegramListener thread]
                                    |
                                    v
                          [engine.ingest_message]
                           /        |         \
                          v         v          v
                    [SQLite]   [Soul-Map]  [AlertEngine]
                          \        |         /
                           v       v        v
              [GET /api/message-intel]  [cockpit card]  [/api/alerts]
                          |
                          v
                   [Jinja message_intel on /]
```

---

## Composer file list

| Action | Path |
|--------|------|
| NEW | `cursor-agents-communication/phase-m-design.md` |
| NEW | `internal/message_intel/context.py` |
| NEW | `internal/message_intel/listener_service.py` |
| NEW | `internal/message_intel/signals_bridge.py` |
| EDIT | `message_intel/models.py` — dedup column + `save_message` idempotency |
| EDIT | `message_intel/telegram_listener.py` — direct callback vs HTTP forward |
| EDIT | `internal/message_intel/engine.py` — dedup response + signals bridge |
| EDIT | `internal/message_intel/routes.py` — `GET /api/message-intel` |
| EDIT | `server.py` — lifespan listener + Jinja context |
| NEW | `tests/test_phase_m_social.py` |
| EDIT | `tests/test_endpoint_contract.py` — contract route |

---

## Key function signatures

```python
# internal/message_intel/context.py
def build_message_intel_context(*, limit: int = 20) -> Dict[str, Any]: ...

# internal/message_intel/listener_service.py
def start_message_intel_listeners() -> bool: ...
def stop_message_intel_listeners() -> None: ...

# internal/message_intel/signals_bridge.py
def emit_social_alert_if_needed(
    message_id: int,
    payload: Dict[str, Any],
    verdict: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Optional[Dict[str, Any]]: ...

# message_intel/models.py
def save_message(self, msg: Dict[str, Any]) -> tuple[int, bool]: ...  # (id, deduped)

# routes
GET /api/message-intel?limit=50&offset=0
```

---

## Composer acceptance checklist

- [x] `GET /api/message-intel` → `{status, messages: [], meta}` honest-empty — **#136**
- [x] Duplicate `(source, group_id, message_id)` → same id, `deduped: true` — **#136**
- [x] Listener starts on lifespan when creds set + `MESSAGE_INTEL_LISTENER!=off` — **#136** (prod: off until Telegram session on volume)
- [x] `message_intel` cockpit section live when DB has rows — **#136**
- [x] `/health` OK; no credentials in code
- [x] Tests pass — `tests/test_phase_m_social.py`
- [x] Social sentiment rollup on homepage — **#217**
