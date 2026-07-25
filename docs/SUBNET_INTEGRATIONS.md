# Bittensor subnet integrations (SN22 / SN64 / SN118)

Primary three on the status banner: marketing badges + optional DeSearch evidence on the Featured Call.

## Verdict (pricing vs cut)

| SN | Name | Free tier? | Cost | Cut / keep | Role on site |
|----|------|------------|------|------------|--------------|
| **118** | Ditto | Yes (dogfood) | $0 | **Keep** | Memory layer; always shows Connected |
| **22** | DeSearch | Free credits at signup | ~$0.10/100 web searches | **Keep — priority key** | Social/web evidence on daily pick |
| **64** | Chutes | No (ended 2026) | $10/mo Plus or PAYG tokens | **Keep if chat matters** | Council chat LLM (`chat_service.py`) |
| **50** | Synth | No | **$49/mo** Standard | **Removed from banner** | Deferred — too expensive for now |

**Recommendation:** Set `DESEARCH_API_KEY` first. Set `CHUTES_API_KEY` if you want live LLM chat. Synth is not shown on the banner; it may still appear in TaonSquare **candidates**.

## Where it shows on the site

1. **Status bar** — under the nav: `Built on Bittensor` + Connected / Reachable / Offline chips (3 subnets)
2. **Footer card** — `Integrations` shows `N/3` connected
3. **Corner panel** — bottom-right (candidates + detail)
4. **API** — `GET /api/subnet-integrations` (includes `desearch_spend` totals)
5. **Ops** — `GET /api/ops/desearch-spend?recent=25` (full ledger)

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
- **Chutes** → chat only; status probe does not call chat
- **Ditto** → status only

DeSearch shows **Connected** when `DESEARCH_API_KEY` is set and the API is reachable (key rejected → not connected).

## Get API keys

### DeSearch (SN22) — do this first

1. [DeSearch Console](https://console.desearch.ai/) → create API key
2. Free credits to test (no card required per their docs)
3. Set secret:
   ```bash
   flyctl secrets set DESEARCH_API_KEY=your_key --app subnet-dashboard
   ```
   Or use [Fly secrets UI](https://fly.io/apps/subnet-dashboard/secrets).

### Chutes (SN64) — for live chat

1. [chutes.ai](https://chutes.ai/) → sign up → API Keys
2. Plus **$10/mo** or top-up PAYG balance
3. ```bash
   flyctl secrets set CHUTES_API_KEY=your_key --app subnet-dashboard
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
| `internal/integrations/clients.py` | DeSearch snippet + AI summary |
| `internal/integrations/desearch_spend.py` | Header billing ledger + ops summary |
| `internal/integrations/desearch_http.py` | DeSearch auth + `desearch_request()` wrapper |
| `internal/integrations/enrichment.py` | Evidence drivers for daily pick |
| `static/js/subnet_integrations.js` | Status bar + corner UI |
| `internal/simivision/chat_service.py` | Chutes LLM for chat |

## Next subnets (TaonSquare)

See `GET /api/subnet-integrations` → `candidates` (51 live+API subnets ranked). Wave B: SN6 Numinous, SN13 Data Universe, SN43 Graphite.
