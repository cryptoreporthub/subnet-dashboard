# Finish queue — single-agent plan (post-rebuild)

**Created:** 2026-07-29  
**Mode:** One Cloud Agent + Grok subagent (Agent A retired per `model-guide.md`)  
**Baseline main:** `c0585ee` — #605 SS-TG stale feed backfill · #604 trending · #603 live-cache proxy · #602 readiness proxy · #601 learning deploy check  
**Canon:** `board.md` · `post-audit-sprint-plan.md` · `full-roadmap-master-plan.md` · `track1-soak-lock.md`

---

## Executive summary

Structural rebuild is **done** (post-audit A–H, worker split v2, pump peers/combined angles, SS-TG W0–W6 code). Remaining work is:

1. **Human gates** — 390px SS-TG sign-off, soak day 7/14, optional secrets
2. **Ops polish** — blockmachine cache on worker, board/doc sync, freshness badge truth
3. **Monitor** — nightly pick audit, combined-angles effectiveness data
4. **Gated** — Phase 4 accuracy lift (after 2026-08-04 soak GO)

**Do not** reopen two-agent parallel mode unless `server.py` conflict is unavoidable.

---

## Prod snapshot (2026-07-29)

| Signal | Status |
|--------|--------|
| `worker_peer.alive` | `true` (split_v2, HTTP probe) |
| Learning loop | `ok` — resolver tick fresh |
| Telegram listener | `running` — OfficialSubnetSummer |
| Readiness | `ready: true` but may flag `live_subnets_cache_empty` / `subnet_feed_registry_only` when blockmachine cache empty on worker |
| TMC feed | ~129 subnets (works) |
| Blockmachine cache | `live_subnets.json` often empty — **root fix in Slice 1** |

---

## Human lane (never delegate)

| # | Task | When | Unblocks |
|---|------|------|----------|
| H1 | **390px Subnet Summers sign-off** — expand message, HC strip, proof band | Now | SS-TG flagship “done” |
| H2 | **Track 1 soak day 7** — GO / HOLD / adjust | 2026-08-04 | Phase 4 accuracy lift |
| H3 | **Track 1 soak day 14** — final sign-off | 2026-08-11 | Accuracy experiments |
| H4 | **Ditto verify** — pump fetch disabled, Health Monitor artifact mode | One-time | Clean automation logs |
| H5 | **W6 bot** — Bot API token + mod perms in Summers | When ready | Enable `TELEGRAM_SUMMARY_BOT` |
| H6 | **`TAOSTATS_API_KEY`** (optional) | Anytime | Clears readiness warning |
| H7 | **`WRITE_API_TOKEN`** (optional) | Anytime | Locks write endpoints |

**H1 checklist** (`subnet-summers-telegram-lock.md` W0 AC):

- [ ] `#section-message-intel` visible without opening `<details>`
- [ ] Subnet Summers branding + t.me link
- [ ] Status rail: live · group · N stored · HC count
- [ ] Yesterday leader card
- [ ] Message expand shows verdict + price snapshot
- [ ] HC strip → Living Focus handoff
- [ ] Outcomes proof band visible

---

## Agent execution order

```text
Slice 0–3  DONE (board, blockmachine, freshness, soak snapshot)
Slice 4–7 + polish  → see pre-aug4-polish-plan.md (active execution plan)
  PR1  Slice 4 combined effectiveness
  PR2–10  SS-TG V5 · listener+empty kit · topic chips · hero D+C-lite
           · sticky spine · evidence panels · /pump parity · mindmap · LF CTAs
  PR-R Slice 5 (only after H1 fails)
  Aug 4 H2 → PR11+ Slice 7a (gated)
```

**Active plan:** `pre-aug4-polish-plan.md` (branch suffix `-6063`).

**Merge cadence:** one PR per slice → merge → `./scripts/babysit_phase.sh c` + `./scripts/check_learning_loop.sh` → Ditto STATUS.

**Branch naming:** `cursor/<slice-slug>-6063` (this wave)

---

## Slice 0 — Doc hygiene

**Problem:** `board.md` has unresolved merge conflict; locks stale vs `main=c0585ee`.

| Work | Files |
|------|-------|
| Resolve board conflict; update main SHA, #602–#604 DONE | `cursor-agents-communication/board.md` |
| Mark fly-worker-split-v2 open items | `fly-worker-split-v2-lock.md` |
| Close learning-loop-verdict-fix lock | `learning-loop-verdict-fix-lock.md` |

**Branch:** `cursor/finish-slice0-board-sync-1d2f`  
**AC:** No `<<<<<<<` markers; board matches prod; Ditto `save_memory` STATUS

---

## Slice 1 — Blockmachine cache on worker (priority)

**Problem:** `data/live_subnets.json` empty on worker → STALE badge, readiness issues. TMC works; on-chain cache does not.

**Root cause (suspected):** `WORKER_HEAVY=essential` in `fly.worker-v2.toml` + `worker.py` treats `"essential"` as `heavy=True` but `background_boot` docstring says essential = **skip** live-subnet wedge. Worker entrypoint defaults `WORKER_HEAVY=essential`; dedicated worker should run **full** heavy feeds on volume.

| Work | Files |
|------|-------|
| Fix `WORKER_HEAVY` semantics: worker mode → heavy feeds unless `off` | `internal/worker.py`, `internal/background_boot.py` |
| Worker entrypoint default `WORKER_HEAVY=full` | `scripts/fly_worker_entrypoint.sh` |
| Optional: `fly.worker-v2.toml` process-specific env | `fly.worker-v2.toml` |
| Bootstrap: `bootstrap_live_subnets_cache()` calls `_sync_once()` on worker boot | `internal/live_subnets.py` |
| Use `DATA_DIR` for cache path (not hardcoded `data/`) | `internal/live_subnets.py` |
| Env `LIVE_SUBNETS_BOOT_IMMEDIATE=on` on worker | fly config |
| Tests | `tests/test_background_boot.py`, `tests/test_live_subnets.py` (new if needed) |

**Branch:** `cursor/finish-slice1-blockmachine-warm-1d2f`  
**AC:**

- Worker writes `live_subnets.json` within ~5 min of boot
- `curl …/api/data-freshness` (via worker proxy from web) shows `subnet_count > 0`
- Readiness `issues` does not include false `live_subnets_cache_empty` when feed healthy
- `./scripts/check_learning_loop.sh` exit 0

**Babysit:**

```bash
curl -fsS https://subnet-dashboard.fly.dev/api/data-freshness | jq '{subnet_count,stale,effective_source,effective_total}'
curl -fsS https://subnet-dashboard.fly.dev/api/ops/readiness | jq '{ready,issues,live_cache,subnet_feed}'
```

---

## Slice 2 — Freshness badge UX

**Problem:** §27-1 rule — never LIVE + stale simultaneously.

| Work | Files |
|------|-------|
| Badge states: LIVE / SNAPSHOT / STALE from proxied `effective_source` + blockmachine age | `static/js/data_freshness.js` |
| Ops readiness badge alignment | `static/js/ops_readiness_badge.js` |
| Honest copy when TMC-only (blockmachine warming) | `templates/partials/premium/header.html` if needed |

**Branch:** `cursor/finish-slice2-freshness-badge-1d2f`  
**Gate:** After Slice 1 deploy, or ship with honest STALE copy if blockmachine still warming  
**AC:** Manual check — badge matches `/api/data-freshness`; no contradictory LIVE+stale

---

## Slice 3 — Soak snapshot script

**Purpose:** One command for human day 7/14 review (`track-1-soak-review-lock.md`).

| Work | Files |
|------|-------|
| Script prints GO/HOLD checklist JSON | `scripts/soak_review_snapshot.sh` (new) |
| Document in lock | `track-1-soak-review-lock.md` |

**Branch:** `cursor/finish-slice3-soak-snapshot-1d2f`  
**AC:** Script exit 0 with structured output; queries match lock queries  
**Non-goals:** No scoring/calibration changes

---

## Slice 4–6 + polish — superseded by active plan

**See:** `pre-aug4-polish-plan.md` (full AC, PR1–10, Aug 4 gate).

| Old slice | Now |
|-----------|-----|
| Slice 4 combined effectiveness | **PR1** — ship measurement now (weights frozen) |
| Slice 5 SS-TG 390px | **PR-R** — only after H1 fails |
| Slice 6 hero visual | **PR5** — locked **D + C-lite** (phase mesh + progress arc) |

---

## Slice 7 — Phase 4 accuracy lift (GATED)

**Gate:** 2026-08-04 day-7 soak **GO** (or explicit early sign-off).

| Slice | Intent | Lock |
|-------|--------|------|
| 7a | Measurement dashboard artifact (7d/30d by expert/regime) | Create `accuracy-lift-lock.md` |
| 7b | Weight audit — online path only | same |
| 7c | Capped scoring experiments — separate PRs each | same |

**Pre-read:** `s25-calibration-oracle-plan.md`, #551 calibration on main  
**NON-GOALS:** LLM nightly trade grader, auto-merge from automation

---

## Optional backlog (no priority until slices 0–3 done)

| Item | Branch idea | Notes |
|------|-------------|-------|
| GHA Slack/email on ops-evidence exit 2 | `cursor/ops-paging-1d2f` | After soak proves signal quality |
| Pick audit MISS investigator | Human Cursor Automation | Prompt in `pick-audit-lock.md` |
| Merge draft PR #532 (Ditto handoff docs) | docs only | |
| Triage #449, #455, #474, #423, #487 | revive or close | Human decision |
| Custom domain + CDN | `DEPLOY.md` | Human DNS |

---

## Explicitly out of scope

- Chutes billing / live LLM chat replies
- Two parallel agents (unless emergency)
- Accuracy/scoring experiments before soak GO
- Rebuilding worker split v2 or resurrecting `server_original.py`

---

## Conflict surface (single agent — still mind these)

| File | Rule |
|------|------|
| `server.py` | One slice at a time; add routes + contract test together |
| `tests/test_endpoint_contract.py` | Add route when adding endpoint |
| `data/*.json` | Never commit local churn |

---

## Babysit contract (every merge)

```bash
BASE=https://subnet-dashboard.fly.dev
./scripts/babysit_phase.sh c
./scripts/check_learning_loop.sh
curl -fsS $BASE/api/ops/readiness | jq '{ready,issues,worker_peer,live_cache,subnet_feed}'
```

---

## Ditto hygiene (after each slice)

1. `save_memory` — short STATUS (`main=<sha>`, slice done, open PR)
2. Update `board.md` Active section
3. Do not use stale Jul 27 pump-desk-automation WARN memories

---

## Approval template (human)

```text
Slice N APPROVED — merge verified, babysit green. Proceed to Slice N+1.
```

```text
Slice N HOLD — [reason]. Fix before next slice.
```

```text
Phase 4 UNGATED — day-7 soak GO. Proceed to Slice 7a.
```
