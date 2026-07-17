# Post-§29 — Automated build plan (agent queue)

**Status:** READY  
**Updated:** 2026-07-17  
**Baseline:** `main` post-#312  
**Backlog:** `post-s28-backlog.md`  
**Human items:** H1–H6 in backlog — **not in this queue**

## Agent prompt (paste once per session)

```
POST-§29 AUTOMATION:
- Read board.md → STATUS.md → this file → active slice AC only.
- One slice per turn. Branch: cursor/post-s29-<slug>-c3fd off latest main.
- Ready PR · merge when CI green · auto-continue next slice.
- No data/*.json commits · ponytail minimal diff.
- Skip human gate items (H1–H6). Skip deferred (D1–D7) unless user asks.
```

## Queue (sequential · unattended)

| # | Slice | Branch slug | State |
|---|-------|-------------|-------|
| **§29-0** | Board + STATUS sync | `post-s29-board-sync-c3fd` | ⏳ next |
| **§29-1** | Prod verify extensions | `post-s29-verify-prod-c3fd` | pending |
| **§29-2** | `?focus=` deep link | `post-s29-focus-deeplink-c3fd` | pending |
| **§29-3** | Name integrity (B1–B4) | `post-s29-name-integrity-c3fd` | pending |
| **§29-4** | Living Focus weight lean (T1) | `post-s29-focus-weights-c3fd` | pending |
| **§29-5** | Wallet rug flags (T3) | `post-s29-wallet-rug-c3fd` | pending |
| **§29-6** | Investigation ask presets (T4) | `post-s29-inv-ask-c3fd` | pending |
| **§29-7** | merged_data pick path (T5) | `post-s29-merged-picks-c3fd` | pending |
| **§29-8** | Pro drawer judges (T6) | `post-s29-pro-judges-c3fd` | pending |
| **§29-9a** | Test debt — judges/simivision | `post-s29-tests-a-c3fd` | pending |
| **§29-9b** | Test debt — phase2/learning | `post-s29-tests-b-c3fd` | pending |
| **§29-10** | Flow graph v2 (T2, optional) | `post-s29-flow-graph-c3fd` | pending · skip if T2 acceptable |

**Out of scope:** P3 (close PRs — one-time manual), H1–H6, D1–D7, E3

---

## §29-0 — Board + STATUS sync

**AC:**
- [ ] `board.md` — main=`6c9b057`, §27/§28 complete, §29 queue active
- [ ] `STATUS.md` — one-line reflects post-#312 state
- [ ] Link to `post-s28-backlog.md` + this file

**Files:** `cursor-agents-communication/board.md`, `STATUS.md`

---

## §29-1 — Prod verify extensions

**AC:**
- [ ] `verify_prod.sh` curls `GET /subnet/1` + `GET /api/search?q=1` (200)
- [ ] Optional: `GET /wallet/{fixture_ss58}` smoke (200, not 5xx)
- [ ] Document in script header

**Files:** `scripts/verify_prod.sh`

---

## §29-2 — `?focus=` deep link

**AC:**
- [ ] Homepage reads `?focus=` or `?netuid=` on load
- [ ] Sets `LivingFocus` / investigation default without full reload
- [ ] Scrolls to `#section-living-focus` when param present
- [ ] Subnet page CTA `/?focus=N` works end-to-end

**Files:** `static/js/living_focus.js`, optional `cockpit_hydrate.js`

---

## §29-3 — Name integrity (B1–B4)

**AC:**
- [ ] `enrich_subnet_row` / SimiVision top never emit `SNNone` or null display names
- [ ] SN82 resolves to on-chain/TaoStats name when key set (else honest `SN82`)
- [ ] Daily-pick candidate vs audited pick names match registry enrichment
- [ ] Test: `test_subnet_names.py` + simivision name contract

**Files:** `internal/subnet_names.py`, simivision routes/engine, `daily_pick_engine.py`, tests

---

## §29-4 — Living Focus weight lean (T1)

**AC:**
- [ ] “Who drives” row on Living Focus from `/api/calibration/status` expert_weights
- [ ] Top expert + bar for focus call; secondary to judge contention
- [ ] RF-2: no win-rate copy

**Files:** `static/js/living_focus.js`, `council_first.css`

---

## §29-5 — Wallet rug flags (T3)

**AC:**
- [ ] Wallet share page shows ruggers risk for top exposure subnets (≤3)
- [ ] Honest-empty when `/api/ruggers/subnet/{n}` dark
- [ ] Link exposure bars → `/subnet/{n}`

**Files:** `internal/share_pages/routes.py`, `templates/share/wallet_page.html`

---

## §29-6 — Investigation ask presets (T4)

**AC:**
- [ ] Owner-check preset calls `/api/investigate/subnet/{focus}/owner-check` with top seller wallets
- [ ] At least one preset uses `POST /api/investigate/ask` with focus netuid
- [ ] Chat explains table; table remains primary

**Files:** `static/js/investigation_panel.js`

---

## §29-7 — merged_data pick path (T5)

**AC:**
- [ ] `get_or_create_today_pick` / story_path / simivision read subnets via shared helper (merged or live)
- [ ] No pick-time snapshot using stale registry-only when chain feed live
- [ ] One test asserting pick subnet row has `sources` when chain primary

**Files:** `server.py`, `fetchers/merged_data.py`, `daily_pick_engine.py`, test

---

## §29-8 — Pro drawer judges (T6)

**AC:**
- [ ] Opening `#pro-cockpit` loads `/api/judges` for focus netuid OR top-12 without blocking home
- [ ] `premium_judges.js` hydrates panel; honest-empty on failure
- [ ] Home hydrate still does not fetch full league on load

**Files:** `static/js/premium_judges.js`, `templates/partials/premium/judges.html`

---

## §29-9a — Test debt (judges / simivision)

**AC:**
- [ ] `test_judges.py`, `test_simivision.py` run against current `server:app` APIs (no `server_original`)
- [ ] Skip or delete tests for routes that no longer exist
- [ ] `pytest tests/test_judges.py tests/test_simivision.py` green

---

## §29-9b — Test debt (phase2 / learning loop)

**AC:**
- [ ] Same for `test_phase2.py`, `test_learning_loop_fixes.py`, `test_simivision_engine.py` — fix or mark xfail with issue ref
- [ ] No regression in `test_endpoint_contract.py`

---

## §29-10 — Flow graph v2 (optional)

**AC:**
- [ ] Wallet page: simple SVG or canvas edges wallet → top 3 subnets by TAO
- [ ] Defer if exposure bars sufficient — human gate “graph worth it”

**Files:** `templates/share/wallet_page.html`, `static/js/wallet_flow_graph.js`

---

## Contract (each slice)

1. Branch `cursor/post-s29-<slug>-c3fd` off latest `main`
2. Ready PR · `pytest tests/test_endpoint_contract.py` green
3. No `data/*.json` commits
4. Update this table row on merge only
5. Auto-continue to next row

## Token discipline

Same as §27 — plan file is cache; git diff is truth; Grok only on AC fail.
