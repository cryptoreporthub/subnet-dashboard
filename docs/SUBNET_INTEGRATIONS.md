# Bittensor subnet integrations (SN22 / SN50 / SN64 / SN118)

Primary four integrations: marketing badges + optional data enrichment on the Featured Call evidence layer.

## Verdict (pricing vs cut)

| SN | Name | Free tier? | Cost | Cut / keep | Role on site |
|----|------|------------|------|------------|--------------|
| **118** | Ditto | Yes (dogfood) | $0 | **Keep** | Memory layer; always shows Connected |
| **22** | DeSearch | Free credits at signup | ~$0.10/100 web searches | **Keep — priority key** | Social/web evidence on daily pick |
| **64** | Chutes | No (ended 2026) | $10/mo Plus or PAYG tokens | **Keep if chat matters** | Council chat LLM (`chat_service.py`) |
| **50** | Synth | No | **$49/mo** Standard (100 credits) | **Defer** unless you pay | Macro BTC 24h skew only; not per-subnet |

**Recommendation:** Set `DESEARCH_API_KEY` first (best ROI). Set `CHUTES_API_KEY` if you want live LLM chat. Skip `SYNTH_API_KEY` until you want to pay $49/mo — badge stays **Reachable** without it.

## Where it shows on the site

1. **Status strip** — below the Featured Call / pulse: `Built on Bittensor` · five status dots · `5/5 live` (names on desktop)
2. **Footer** — `Integrations` shows `N/5` connected
3. **API** — `GET /api/subnet-integrations` (60s cache; parallel probes)
4. **Ops** — `GET /api/ops/desearch-spend?recent=25` (full ledger)

The floating corner panel was removed — it competed with the first viewport.

## DeSearch spend tracking

Every DeSearch HTTP response is parsed for billing headers:

- `X-Desearch-Cost-Usd` — charge for the call
- `X-Desearch-Usage-Count` — billed items (per source; min 10)
- `X-Desearch-Service` — e.g. `web_search`, `ai_search`

Totals persist to `data/desearch_spend.json` on Fly (volume mount). Override with `DESEARCH_SPEND_PATH`. Probes, evidence snippets, and AI search all record via `desearch_request()` / `_http_probe()`.

```bash
curl localhost:50745/api/ops/desearch-spend | python3 -m json.tool
```

## Evidence wiring (when keys exist)

- **DeSearch** → `integration_evidence_drivers()` adds a `social` chip on the Featured Call (`dpick_copy.py`)
- **Synth** → adds macro `Synth BTC 24h …` driver (tape context, not subnet-specific)
- **Chutes** → chat only; status probe does not call chat
- **Ditto** → status only

## Get API keys

### DeSearch (SN22) — do this first

1. [DeSearch Console](https://console.desearch.ai/) → create API key
2. Free credits to test (no card required per their docs)
3. Set secret:
   ```bash
   flyctl secrets set DESEARCH_API_KEY=your_key --app subnet-dashboard
   ```

### Chutes (SN64) — for live chat

1. [chutes.ai](https://chutes.ai/) → sign up → API Keys
2. Plus **$10/mo** or top-up PAYG balance
3. ```bash
   flyctl secrets set CHUTES_API_KEY=your_key --app subnet-dashboard
   ```

### Synth (SN50) — optional paid

1. [dashboard.synthdata.co](https://dashboard.synthdata.co/choose-plan/) → Standard $49/mo+
2. Only set if you want macro forecast drivers:
   ```bash
   flyctl secrets set SYNTH_API_KEY=your_key --app subnet-dashboard
   ```

### Ditto (SN118)

No key needed. Status probe marks Connected as SN118 dogfood.

## Local dev

```bash
cp .env.example .env
# edit keys, then:
export $(grep -v '^#' .env | xargs)
python server.py
curl localhost:50745/api/subnet-integrations | python3 -m json.tool
```

## Code map

| File | Purpose |
|------|---------|
| `internal/integrations/status.py` | Live probes + `/api/subnet-integrations` |
| `internal/integrations/clients.py` | DeSearch snippet + AI summary + Synth macro |
| `internal/integrations/desearch_spend.py` | Header billing ledger + ops summary |
| `internal/integrations/desearch_http.py` | DeSearch auth + `desearch_request()` wrapper |
| `internal/integrations/enrichment.py` | Evidence drivers for daily pick |
| `static/js/subnet_integrations.js` | Status bar + corner UI |
| `internal/simivision/chat_service.py` | Chutes LLM for chat |

## Next subnets (TaonSquare)

See `GET /api/subnet-integrations` → `candidates` (51 live+API subnets ranked). Wave B: SN6 Numinous, SN13 Data Universe, SN43 Graphite.
