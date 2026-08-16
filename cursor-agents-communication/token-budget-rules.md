# Token budget rules — RETIRED (2026-08-16)

Human request: drop billing-cycle **brevity** (short Grok LOCK, Composer-fast-only, cite-don’t-paste replies). Agents write at natural length.

The always-on Cursor rule `.cursor/rules/token-budget.mdc` was **deleted**.

## Still in force (not brevity)

- **`.cursorignore`** — do not pull `data/*.json`, `.venv`, caches, or superseded design dumps into context.
- **Billing watch** — check [cursor.com/dashboard/usage](https://cursor.com/dashboard/usage) after heavy runs. Stop and tell the human if new rows show **On-Demand $** beyond the included pool, or if On-Demand spend is climbing in [billing](https://cursor.com/dashboard/billing).

Historical §18 one-agent / Composer-fast / short-LOCK tables lived in git history of this file. Do not re-apply them unless the human asks.
