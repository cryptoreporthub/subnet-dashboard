# P2 — Telegram listener (document only)

**Recorded:** 2026-08-24. **Do not enable.** This is config/ops documentation, not a code change to start the listener.

## Effective config (no secrets)

| Layer | What it does |
|---|---|
| `fly.toml` `[env]` | `MESSAGE_INTEL_LISTENER = "auto"` — process env **overrides** this. |
| Process / Fly secrets | `MESSAGE_INTEL_LISTENER` in `{off, false, 0, no}` → `_listener_enabled()` is false. Prod `reason:"disabled"` means the **running process** has the flag off, even if toml says `auto`. |
| Credentials | `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` (names in `listener_status`: `has_creds`). Presence ≠ enabled. |
| Session | `has_session` from `_has_session_file()`; `session_mode` from `telegram_session_mode()` (string vs volume `.session`). |
| Telethon | `telethon_available` from optional `message_intel.telegram_listener.HAS_TELETHON`. |
| Heartbeat | `MESSAGE_INTEL_LISTENER_HEARTBEAT` (default `data/.message_intel_listener`). |

Code: `internal/message_intel/listener_service.py` (`_listener_enabled`, `listener_status`). Boot: `internal/background_boot.py` also reads `MESSAGE_INTEL_LISTENER`.

## How to read `listener_status` (honest)

- `enabled: false` + `reason: "disabled"` → **config/env**, not a crash.
- `missing_telegram_creds` / `telethon_unavailable` / `missing_session` / `idle_not_started` / `listener_stopped` / `group_not_connected` are separate reasons.
- Store can still hold historical messages while the listener is disabled (prod last msg ~Aug 21 with `enabled:false` is consistent with a stopped ingest, not with `/subnetsummer` 500).

## Not this ticket

- Do not flip `MESSAGE_INTEL_LISTENER` to on.
- Do not treat `/subnetsummer` 500 as a Telegram enablement bug (`/listener` is 308 → `/subnetsummer`; 500 was SSR/render).
- Do not paste session strings or API hashes into docs, PRs, or Ditto.
