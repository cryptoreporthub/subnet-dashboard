# Deploy Notes

## 2026-09-10

Deploy vehicle: carries PR #1262 (summary bot `/help` + `/start`) to Fly.

- `build_help_text()` compact command reference wired to `/help` and `/start`
- Chats register for trend alerts via the existing command path (no change)
- No behavior changes to existing commands

Previous vehicles: #1261 (trend watcher live + TELEGRAM_TREND_ALERT=on), #1259/#1260.
