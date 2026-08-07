# Subnet Dashboard

A Bittensor subnet intelligence dashboard built with FastAPI. Tracks whale movements, watchlists, portfolios, council judge verdicts, and subnet analytics.

## Stack

- **Backend:** Python 3.12, FastAPI, Uvicorn
- **Templates:** Jinja2
- **Scheduler:** APScheduler (background data refresh)
- **Rate limiting:** SlowAPI
- **Monitoring:** Sentry, Prometheus

## Running on Replit

The **Start application** workflow runs:

```
uvicorn server:app --host 0.0.0.0 --port 5000
```

All external API keys are **optional** — the app degrades gracefully without them. To unlock premium features, set secrets in the Replit Secrets tab:

| Secret | Purpose |
|---|---|
| `DESEARCH_API_KEY` | SN22 DeSearch — social/web evidence |
| `SYNTH_API_KEY` | SN50 Synth — BTC/ETH macro forecasts |
| `CHUTES_API_KEY` | SN64 Chutes — LLM for council chat |
| `CHUTES_BASE_URL` | Chutes API base URL |
| `CHUTES_MODEL` | Chutes model name |

## Key Files

- `server.py` — main FastAPI app and route registration
- `internal/` — feature modules (whales, watchlist, portfolio, council, etc.)
- `templates/` — Jinja2 HTML templates
- `static/` — frontend assets
- `requirements.txt` — Python dependencies

## Notes

- Originally deployed on Fly.io (`fly.toml`); deployment config is preserved but not used on Replit
- A circular import warning on startup (`MindmapBridge`) is non-fatal — the app starts fine

## User preferences

- **Mobile-first design**: this is a mobile-first site. Build and verify UI against narrow/phone viewports first, then scale up to desktop — not the reverse. When changing layout/visuals, confirm nothing breaks or clips at phone width.
