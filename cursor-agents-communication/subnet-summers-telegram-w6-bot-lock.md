# LOCK — SS-TG W6 In-chat /summary bot

**Status:** BUILD  
**Slice:** SS-TG W6 (Phase G)  
**Branch:** `cursor/phase-g-ss-tg-w6-bot-1d2f`  
**Gate:** Human sets `TELEGRAM_BOT_TOKEN` + adds bot to Summers group with post permission

## Scope

| Item | Detail |
|------|--------|
| Module | `internal/message_intel/summary_bot.py` — Bot API long-poll, `/summary` command |
| Data | Reuses `build_24h_summary()` from `internal/message_intel/rollup.py` |
| Boot | `background_boot._maybe_start_summary_bot()` when `TELEGRAM_SUMMARY_BOT=on` + token |
| Env | `TELEGRAM_SUMMARY_BOT=off` default in `fly.toml` |
| Rate limit | 1 `/summary` per chat per 5 minutes |
| Desk link | `APP_BASE_URL/#section-message-intel` (fallback fly.dev) |

## Out of scope

- Does **not** replace Telethon user-session listener (`MESSAGE_INTEL_LISTENER`)
- Does **not** steer council daily pick from chat (quarantined)
- No new HTTP routes (contract unchanged)

## Acceptance

- [ ] `/summary` in test/staging group posts formatted 24h rollup + desk link
- [ ] Rate limit reply when spammed
- [ ] Bot off by default in prod env
- [ ] `tests/test_summers_telegram_w6_bot.py` green with mocks

## Verify

```bash
pytest tests/test_summers_telegram_w6_bot.py -q
# Human (after secrets):
# fly secrets set TELEGRAM_SUMMARY_BOT=on TELEGRAM_BOT_TOKEN=... --app subnet-dashboard
# Post /summary in OfficialSubnetSummer
```

## Babysit

Human posts `/summary` in OfficialSubnetSummer; confirm bot reply + site link. Check fly logs for `Telegram summary bot polling started`.
