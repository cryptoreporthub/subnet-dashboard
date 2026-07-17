# §27 — Automated build plan (unattended queue)

**Status:** IN PROGRESS  
**Updated:** 2026-07-17  
**Baseline:** `main` post-#307 · §27-1 in PR #310  
**Models:** Composer 2.5 / 2.5-fast build · Grok subagent slow+low **only** if AC fails  
**Spec:** `s27-trust-and-brain-plan.md` (LOCKED — do not re-plan)

## Agent prompt (paste once per session)

```
§27 AUTOMATION (Pro+ token-save):
- Read board.md → STATUS.md → this file → active slice AC only.
- One slice per turn. Git diff is cache — do not re-audit merged slices.
- Skip Grok when slice is LOCKED below. Grok slow+low only on AC FAIL.
- Branch: cursor/s27-<slice>-c3fd off latest main (or stack on open §27 PR if not merged).
- Ready PR · merge when CI green · auto-continue next slice.
- Obey .cursorignore — never commit data/*.json.
- Stop + notify human if On-Demand $ on usage dashboard.
```

## Queue (sequential · unattended)

| # | Slice | Branch | PR | State |
|---|-------|--------|-----|-------|
| **§27-1** | Trust shell | `cursor/s27-1-trust-shell-c3fd` | #310 | 🟡 open |
| **§27-2** | Data pipeline | `cursor/s27-2-data-pipeline-c3fd` | — | ⏳ next |
| **§27-3a** | Living Focus | `cursor/s27-3a-living-focus-c3fd` | — | pending |
| **§27-3b** | Prove it | `cursor/s27-3b-prove-it-c3fd` | — | pending |
| **§27-3c** | Public Self-Update | `cursor/s27-3c-self-update-c3fd` | — | pending |
| **§27-4** | Learning hygiene | `cursor/s27-4-learning-hygiene-c3fd` | — | pending |

**After §27:** §28 shareable product (`s28-shareable-product-plan.md`) — human gate “product feels finished.”

**Skip unless asked:** Redis · full Bittensor SDK · F7 DNS · A1b bot · S5 Discord

## Contract (each slice)

1. Branch `cursor/s27-<slug>-c3fd` off latest `main` (rebase if prior §27 PR merged).
2. Ready PR (not draft) · `pytest tests/test_endpoint_contract.py` green.
3. Ponytail minimal diff · no `data/*.json` commits.
4. Update this table + `board.md` + `STATUS.md` on merge only (not every turn).
5. Auto-continue to next row — no human relay.

---

## §27-1 — Trust shell ✅ (PR #310)

**AC:** signals/summary + alerts independent; KPI = trust_banner; LIVE pill honest; no blanket skeletons; portfolio note.

---

## §27-2 — Data pipeline

**AC:**
- [ ] `/api/subnets` `meta.source` reflects blockmachine when chain primary
- [ ] Rows carry `source` / `sources` from live feed
- [ ] `cockpit_hydrate.js` `renderHero` uses inferred source — no hardcoded TAOMARKETCAP
- [ ] `verify_prod.sh` checks `/api/data-freshness` + subnet count

**Files:** `server.py`, `static/js/cockpit_hydrate.js`, `scripts/verify_prod.sh`

---

## §27-3a — Living Focus

**AC:**
- [ ] `#section-living-focus` after story-strip; open (not in drawer)
- [ ] `focus_netuid` from daily-pick; `/api/judges/{focus}` only (no league on home)
- [ ] Contested/agreement visible; expert weight lean
- [ ] ≤3 chrome chips (regime · rug · autopsy) honest-empty
- [ ] SimiVision top-3 switcher reorients focus
- [ ] Story path step 2 → “Council experts”

**Files:** `living_focus.html`, `living_focus.js`, `premium_cockpit.html`, `story_path.py`, `cockpit_hydrate.js`, `council_first.css`

---

## §27-3b — Prove it

**AC:**
- [ ] Sellers/wallet HTML tables + tx links
- [ ] Presets → investigate APIs; default netuid = focus
- [ ] “Prove it” CTA from Living Focus scrolls/opens investigation

**Files:** `investigation_panel.js`, `investigation.html`

---

## §27-3c — Public Self-Update

**AC:**
- [ ] Last-learn strip on focus: grade + expert nudge + before/after weights
- [ ] Replay + Share → existing time-capsule / OG share
- [ ] Honest-empty when no graded beat on focus SN
- [ ] RF-2: no win-rate outside trust_banner

**Files:** extend `living_focus.js`; reuse `time_capsule.js`

---

## §27-4 — Learning hygiene

**AC:**
- [ ] `nudge_expert(expert, correct)` in `internal/council/weights.py`
- [ ] `resolver._nudge_weights` + `LearningEngine.record_feedback` call it
- [ ] Phase N calibration unchanged (batch authority)
- [ ] One small test for nudge_expert

**Files:** `weights.py`, `resolver.py`, `datastore/learning_engine.py`, `tests/test_nudge_expert.py`

---

## Token discipline

See `s27-trust-and-brain-plan.md` § Build discipline. Plan file = cache of record.
