# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-27T17:15:00Z  
**main:** `f7aadc0` — #542 LB-12 focus graph/story strip  
**Handoff:** `ditto-cursor-handoff.md` — Ditto reviews → promote to git lock before Cursor builds

## Active — Brain Trio Revision (`brain-trio-revision-lock.md`)

| Wave | Status | Branch / PR |
|------|--------|-------------|
| W0-A Proof RF-2 honesty | 🔄 in progress | `cursor/brain-trio-revision-1d2f` |
| W0-B Living Focus truth | queued | — |
| W0-C One live story spine | queued | — |
| W0-D Graph taste | queued | — |
| W0-E Placement (mindmap on spine) | queued | — |
| W0-F Stub kill + board DONE | queued | — |

**Loop:** merge → prod smoke → next wave until lock DONE.

## Learning loop audit (2026-07-27)

- Live prod verified via `check_learning_loop.sh` (ok; snapshot not written yet post-boot).
- Hardening merged: #533–#534 (heavy-job gate, resolver web guard, snapshot wedge fix).
- **Fly secrets:** confirm `WORKER_HEAVY=essential` via `flyctl secrets list` (human).

## Pump desk — DONE

| Item | PR |
|------|-----|
| SCAN home + `/pump` flagship | #480, #511 |
| Whale line + BUILDING Telegram | #528 |
| Desk warming / snapshot stability | #533, #534 |

## Post-stability sprint (`post-stability-sprint-plan.md`)

| Wave | Status | PRs |
|------|--------|-----|
| A Verify/G0 | ✅ | #501, prod `g0_phone_qa.sh` 2026-07-26 |
| B Batch 0 | ✅ | #486–#488 |
| C Pump parity | ✅ | #489, #493 |
| D Chat | ✅ | #492–#507 |
| E Integrations | ✅ | **#508** (phased; supersedes #449) |

**Prod verified:** `/health` OK · G0 green · `/api/subnet-integrations/signals` OK · `verify_prod.sh` hardened (readiness timeout → WARN, not abort).

## Telegram intel + outcome loop (#513–#515 on `main`)

Message-intel rollup UI, listener hardening, background price-outcome loop. Session string path: #541.

## Active (other)

| Track | Plan / lock | Gate |
|-------|-------------|------|
| Telegram ingest proof | ops | Human bootstrap / TELEGRAM_SESSION_STRING |
| Living brain LB-12 | `living-brain-lock.md` | ✅ #542 |
| Brain trio quality | `brain-trio-revision-lock.md` | **W0-A…F execute** |
| H1 hour watch | `h1-hour-watch-live-lock.md` | Board clear + G0 |
| Council automations | Ditto Settings | Manual create |

## Communication

See `ditto-cursor-handoff.md` — **promote to lock** after Ditto or Cursor finishes a review.

## Out of scope (skipped)

- Chutes billing / live LLM chat replies (human Fly secrets)

## Ops optional

- `APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh`
- `fly scale count web=1 worker=1 --app subnet-dashboard`
