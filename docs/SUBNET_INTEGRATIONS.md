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

1. **Status bar** — under the nav: `Built on Bittensor` + Connected / Reachable / Offline chips
2. **Footer card** — `Integrations` shows `N/4` connected
3. **Corner panel** — bottom-right (candidates + detail)
4. **API** — `GET /api/subnet-integrations`

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
| `internal/integrations/clients.py` | DeSearch snippet + Synth macro fetch |
| `internal/integrations/enrichment.py` | Evidence drivers for daily pick |
| `static/js/subnet_integrations.js` | Status bar + corner UI |
| `internal/simivision/chat_service.py` | Chutes LLM for chat |

## Next subnets (TaonSquare)

See `GET /api/subnet-integrations` → `candidates` (51 live+API subnets ranked). Wave B: SN6 Numinous, SN13 Data Universe, SN43 Graphite.
