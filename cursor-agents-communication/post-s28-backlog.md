# Post-§28 backlog

**Updated:** 2026-07-17  
**Baseline:** `main` post-#312 (`6c9b057`) — §27 + §28 merged  
**Automation queues:** `post-s29-automated-build-plan.md` (polish) · `post-s30-living-brain-plan.md` (memory→advice)  
**Living Brain audit:** `living-brain-audit.md`

---

## Done (close the loop)

- [x] §27-1 → §27-4 — trust shell, data pipeline, Living Focus, Prove it, Self-Update, `nudge_expert`
- [x] §28-1 → §28-4 thin — `/subnet/{id}`, `/wallet/{ss58}`, search palette, exposure bars
- [x] Merged to `main` via PR #312

---

## Do soon (hygiene + verify ship)

| # | Item | Why |
|---|------|-----|
| P1 | **Prod smoke after deploy** — `./scripts/verify_prod.sh` | Confirms freshness + subnet count + health |
| P2 | **Spot-check new routes** — `/subnet/1`, `/wallet/{ss58}`, Ctrl/Cmd+K | Core §28 deliverable |
| P3 | **Close stale PRs** — #310, #311 if still open | Superseded by #312 |
| P4 | **Refresh `board.md` + `STATUS.md`** | Still referenced pre-merge state |
| P5 | **Wire `?focus={netuid}` on homepage** | Subnet page links `/?focus=N` but JS does not read param yet |

---

## Prod bugs (name / pick integrity)

Discussed in subnet-names / trailblazing investigation; not confirmed fixed on prod:

| # | Item | Notes |
|---|------|-------|
| B1 | **SN82 name** still `SN82` | TaoStats / on-chain identity path |
| B2 | **Daily-pick candidate** wrong name (e.g. SN1 as “Apex”) | Pick vs candidate labeling |
| B3 | **`/api/simivision` null / `SNNone` names** | Blocking for Focus switcher quality |
| B4 | **Conviction peek** when SimiVision names broken | Downstream of B3 |

---

## Shipped thin — polish pass

| # | Item | Gap |
|---|------|-----|
| T1 | **Living Focus “who drives”** | Expert weight lean / bars not explicit |
| T2 | **§28-4 money-flow** | Bars only, not wallet↔subnet graph |
| T3 | **Wallet page rug flags** | §28-2 mentioned; not on wallet template yet |
| T4 | **Investigation presets → `POST /api/investigate/ask`** | Sellers API + chat; ask API partial |
| T5 | **`merged_data` single pick read path** | `/api/subnets` improved; picks may diverge |
| T6 | **Pro drawer judges panel** | Home league removed; verify drawer load |

---

## Explicitly deferred (do not build unless asked)

| # | Item |
|---|------|
| D1 | Redis / Layer-2 cache |
| D2 | Full Bittensor Python SDK |
| D3 | EMA inside `nudge_expert` (batch calibration stays authority) |
| D4 | Real-time sell alerts push |
| D5 | Owner overlay on all reports |
| D6 | Extrinsic deep links everywhere |
| D7 | Full interactive money-flow graph |

---

## Human / infra (out of agent automation)

| # | Item |
|---|------|
| H1 | F7 custom domain — `dashboard.cryptoreporthub.com` (`DEPLOY.md`) |
| H2 | A1b Telegram bot / alert delivery |
| H3 | S5 Discord / X ingest |
| H4 | C1 Telegram listener creds |
| H5 | B12 weekly letter email |
| H6 | Fly volume / region mismatch (if deploy fails) |

---

## Engineering debt (chunked, non-blocking)

| # | Item |
|---|------|
| E1 | Green full test suite — modules still reference `server_original` APIs |
| E2 | Optional background schedulers — resolver, indicators, calibration (env-gated) |
| E3 | Gate 5 Fly validation in CI (skipped by design) |
