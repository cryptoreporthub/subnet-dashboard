# LOCK — Subnet Summers Telegram Flagship

**Status:** IN PROGRESS — W0  
**Approved:** 2026-07-27 (human: “flagship for Subnet Summers launch”)  
**Slice ID:** SS-TG  
**Viewport:** 390px primary  
**Baseline:** Telegram listener **live** · `TELEGRAM_SESSION_STRING` set · ~90+ msgs ingesting from `OfficialSubnetSummer`

## Product job

Subnet Summers members open the site **for Telegram intelligence**. The desk must feel first-class — not buried, not thin, not “ops status.”

What they want:

1. **What’s hot in the group right now** (trending subnets)
2. **Who’s leading the chat** (weekly champions)
3. **What just got said — with conviction** (live feed with jury scores)
4. **Proof it is their group** (Subnet Summers branding + live pulse)
5. Later: **did the call pay?** (graded outcomes on messages)

## Placement (locked)

```text
Council stage (hero)
Pump desk
→ Subnet Summers desk   ← FIRST-CLASS spine (not in More intel drawer)
Council weighing
Living Focus · Proof · Mindmap · Trail
…
```

## Waves

| Wave | What | Status |
|------|------|--------|
| **W0** | Promote onto spine · Summers brand · rich feed · **yesterday's most talked about** | **BUILD** |
| **W1** | Message expand / detail (verdict reasoning + price snapshot / outcome when graded) | next |
| **W2** | High-conviction strip + “Open subnet” / Living Focus handoff | next |
| **W3** | Outcomes proof band for Telegram calls (hit-rate story) | after soak |

## W0 acceptance

- [ ] `#section-message-intel` visible without opening any `<details>`
- [ ] Title brands **Subnet Summers** + link to `https://t.me/OfficialSubnetSummer`
- [ ] Status rail: live · group · N stored · high-conviction count
- [ ] **Yesterday leader** card: prior UTC day top subnet + mentions + runner-up
- [ ] Live feed rows show conviction %, direction, sentiment (not snippet-only)
- [ ] Subnet chips link to `/subnet/{netuid}` when entities present
- [ ] Trending + champions remain; no emoji title clutter
- [ ] Existing APIs only — no new routes required for W0
- [ ] Contract tests still green

## Out of scope (W0)

- Bot posting back into Summers
- Discord / multi-group
- Steering council daily pick from chat (quarantined)
- LLM NLP upgrade

## Verify

```bash
pytest tests/test_endpoint_contract.py tests/test_message_intel_f6.py -q
curl -fsS https://subnet-dashboard.fly.dev/api/message-intel/status
# Home HTML: id="section-message-intel" outside intel-ribs
```
