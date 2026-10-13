# Deploy vehicle — main `57d1c7bb` (Telegram /gainers + setMyCommands + trend chat id)

**Purpose:** Docs-only deploy vehicle. Carries the `fly-deploy` label to trigger
`fly.yml` on merged vehicle PRs (push-to-main deploy disabled).

## What this deploys

Main HEAD at label time:

```
57d1c7bb9a2cb34751c1c0a593f7f2c15bbaa85e
```

Includes [#1390](https://github.com/cryptoreporthub/subnet-dashboard/pull/1390):

- `setMyCommands` for SubnetSummerBot menu parity
- Fast `/gainers` path (`get_merged_subnet_rows_quick`) — avoids >90s merge wedge on poll loop
- Trend/gainers push chat id fallbacks (`TELEGRAM_ALERT_CHAT_ID`, `TELEGRAM_GROUP_ID`)

## Post-deploy gate

- `GET /version` == full SHA above
- `GET /health` 200
- `fly logs` → `Telegram summary bot polling started` (after ~105s boot defer)
- Joshua: `/gainers@SubnetSummerBot` in Summers supergroup

## Authorization

User GO merge + deploy (2026-10-13).
