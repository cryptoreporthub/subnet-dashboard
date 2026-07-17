# Post-§28 backlog

**Updated:** 2026-07-17  
**Baseline:** `main` @ `252161c` — §27–§30 + §29 polish complete  
**Queues:** `master-automated-gameplan.md` (done)

---

## Done

| Area | Status |
|------|--------|
| §27 trust shell + Living Focus + `nudge_expert` | ✅ #312 |
| §28 shareable `/subnet`, `/wallet`, search palette | ✅ #312 |
| §30 Living Brain closure (LB-1…LB-16) | ✅ #314 |
| §29 polish (wallet rugs, inv presets, pick feed, lazy judges) | ✅ #315 |
| P1 verify_prod extensions | ✅ |
| P5 `?focus=` deep link | ✅ #314 |
| B3 SNNone guard + name enrichment | ✅ #314/#315 |
| T1 weight lean on Living Focus | ✅ #314 |
| T3 wallet rug flags | ✅ #315 |
| T4 investigation ask + owner-check | ✅ #315 |
| T5 shared pick subnet feed | ✅ #315 |
| T6 pro drawer judges lazy load | ✅ #315 |
| §29-10 wallet flow SVG (top-3 edges) | ✅ completion PR |

---

## Skipped (human / infra — not agent automation)

| # | Item |
|---|------|
| H1 | Custom domain (`dashboard.cryptoreporthub.com`) — **skipped per user** |
| H2 | Telegram bot / alert delivery |
| H3 | Discord / X ingest |
| H4 | Telegram listener creds |
| H5 | Weekly letter email |
| H6 | Fly volume / region mismatch |

---

## Explicitly deferred (do not build unless asked)

D1–D7 (Redis, Bittensor SDK, EMA nudge, sell-alert push, owner overlay, extrinsic links, full interactive money-flow graph).

---

## Engineering debt (non-blocking)

| # | Item | Notes |
|---|------|-------|
| E1 | Broader test suite | Core contract + judges + simivision + phase2 green |
| E2 | Optional background schedulers | Env-gated |
| E3 | Gate 5 Fly validation in CI | Skipped by design |
