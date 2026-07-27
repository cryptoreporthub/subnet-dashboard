# Brain Trio Revision — Living Focus · Mindmap · Living Brain

**Status:** LOCK ACTIVE — execute until DONE  
**Updated:** 2026-07-27  
**Branch prefix:** `cursor/brain-trio-*-1d2f`  
**Baseline:** `main` @ `f7aadc0` (#542 LB-12 focus graph/story strip shipped)  
**Canon:** quality audit 2026-07-27 · `living-brain-lock.md` (LB-12 ✅) · this file owns remaining product quality

```
VERDICT: CONDITIONAL — loop is real; Focus / Mindmap / Brain UI not best-of-self yet
DECISIONS:
- Honesty before features (RF-2 on Proof before graph polish)
- One story spine (hydrate home cause chain; Pro path stays depth)
- Graph defaults to signal/prediction/weight edges; collapse hold dispositions
- Promote mindmap+trail onto brain spine (out of Market landfill)
- Kill LB-10 stub recommendations
AC: each wave checkbox below; contract + listed pytest green; prod smoke after merge
RISKS / NON-GOALS: confidence/LONG (#491), Telegram, dual portfolio redesign, full money-flow graph
DITTO_REVIEW: e32a6fae
```

---

## North star

| Surface | Best version means |
|---------|-------------------|
| **Living Focus** | Last learn / weight nudge read real trail; bars render; CTAs honest; action badge truthful when focus ≠ daily call |
| **Mindmap** | Readable graph (focus or filtered), one live story spine, trail next to brain — not Market drawer noise |
| **Living Brain** | Proof % only when `trust_banner.ready`; trust banner visible when blocked; letter + cause chain alive |

**Loop:** plan → implement one wave → tests → PR → merge → prod smoke → next wave. Babysit until all waves ✅.

---

## Already done (do not redo)

| Item | PR |
|------|-----|
| §30-1–10 Living Brain backend/UI slices | #526–#529 |
| LB-12 focus-scoped graph + story strip handoff | **#542** |
| `?focus=` / calibration weights / chip scoping | §30 |

---

## Wave queue (strict order)

```text
W0-A  Proof RF-2 honesty          ← ship first
W0-B  Living Focus truth          ← trail evidence + bars + CTAs
W0-C  One live story spine        ← hydrate home cause chain
W0-D  Graph taste                 ← drop hold noise + layout cap
W0-E  Placement                   ← mindmap+trail onto brain spine
W0-F  Stub kill + board sync      ← LB-10 + STATUS/board
DONE  babysit green on prod
```

**Hard rule:** one wave per PR (or tightly coupled pair). Merge before starting next unless blocked on review.

---

## W0-A — Proof RF-2 honesty

**Branch:** `cursor/brain-trio-w0a-proof-rf2-1d2f`  
**Goal:** Big proof % and KPI accuracy never claim trust before integrity gate.

### AC
- [ ] Proof band SSR: show big % only when `trust_banner.ready`; else quiet “Building (n/30)…” / `tb.message`
- [ ] `syncProofBandGraded` / hydrate path: same gate (`ready`)
- [ ] `renderKpi`: accuracy `—` when not `ready` (graded counts OK); integrity message visible
- [ ] Trust banner: **remove `hidden`** when blocked so `tb.message` is readable
- [ ] Test: fixture with `ready=false` + graded>0 → proof HTML quiet, not XX%

### Files
`templates/partials/premium_cockpit.html` · `templates/partials/premium/council_stage.html` · `static/js/cockpit_hydrate.js` · `static/js/trust_banner_ui.js` · `tests/test_living_brain.py` (or new `test_proof_rf2.py`)

---

## W0-B — Living Focus truth

**Branch:** `cursor/brain-trio-w0b-focus-truth-1d2f`

### AC
- [ ] `buildLearnStripHtml` / `weightNudgeFromTrail` read `ev.evidence` (fallback to payload)
- [ ] Prefer `prediction_resolved` / `weight_change` over caution noise for “Last learn”
- [ ] Weight bar `--pct` uses bare number matching CSS `calc(var(--pct)*1%)`
- [ ] Rename “Open share card” → “Open subnet” **or** link real `/share/call/...` when id exists
- [ ] Action badge: if focus ≠ daily-pick netuid → show WATCH / judge consensus, not global HOLD/LONG
- [ ] Collapse triple dissent to one line on mobile
- [ ] Test: trail fixture with `evidence.before/after/correct` → learn strip shows HIT/MISS + nudge

### Files
`static/js/living_focus.js` · `templates/partials/premium/living_focus.html` · `static/css/council_first.css` (if needed) · `tests/test_living_brain.py`

---

## W0-C — One live story spine

**Branch:** `cursor/brain-trio-w0c-story-spine-1d2f`

### AC
- [ ] `story_path_ui.js` hydrates `#section-cause-chain` (home) **and** `#story-path-chain` (Pro)
- [ ] Shared render helper; refresh on `home-daily-call-updated` + `living-focus:change` (optional focus note)
- [ ] Weight step not stuck `pending` when weights exist (`story_path.py`)
- [ ] No third duplicate narrative added
- [ ] Test: cause-chain mount present; JS exports / smoke string assert

### Files
`static/js/story_path_ui.js` · `templates/partials/premium/cause_chain.html` · `internal/learning/story_path.py` · tests

---

## W0-D — Graph taste (graph-lite polish)

**Branch:** `cursor/brain-trio-w0d-graph-taste-1d2f`  
**Depends:** #542 focus API exists

### AC
- [ ] Default (no focus): exclude disposition nodes with `action=hold` **or** collapse into one hub node `holds:N`
- [ ] Cap nodes (~40) preferring prediction / weight_change / disposition_shift / focus ego
- [ ] Focus mode: never dump global holds; ego-net only
- [ ] Detail panel: human line (“weight nudged”, “prediction HIT”) not raw JSON dump
- [ ] Prod smoke: unscoped graph node count ≪ 305 (target &lt; 80)
- [ ] Tests in `test_phase_g_mindmap_graph.py`

### Files
`internal/mindmap/graph.py` · `static/js/mindmap_graph.js` · tests

---

## W0-E — Placement (brain spine)

**Branch:** `cursor/brain-trio-w0e-placement-1d2f`

### AC
- [ ] Move Interactive Mindmap + Trail out of Market drawer into spine after Proof (or Focus)
- [ ] Market drawer keeps scanner/staking/signals — not mindmap/trail
- [ ] Living Focus “Full learning trail →” opens `#section-trail` and ensures parent `<details>` open if any
- [ ] Pro drawer summary hint mentions story path if kept there
- [ ] G0 / visual: mindmap visible without opening Market

### Files
`templates/partials/premium_cockpit.html` · `static/js/living_focus.js` (hash open) · minimal CSS

---

## W0-F — Stub kill + board sync

**Branch:** `cursor/brain-trio-w0f-stub-board-1d2f` (or fold into W0-E if tiny)

### AC
- [ ] `MindmapBridge.get_brain_recommendations` returns honest-empty / real pick engine — **no SN1/2/3 hardcoded**
- [ ] Call sites in `server.py` safe
- [ ] Strip mindmap summary placeholder fluff (`noticed` / `opinion_changes` theater) or mark unused
- [ ] Update `board.md` + `STATUS.md` + this lock → Status: DONE
- [ ] Ditto STATUS post

### Files
`internal/council/mindmap_bridge.py` · `server.py` · `internal/learning/routes.py` · board/STATUS/lock

---

## Babysit checklist (every wave)

```bash
PYTHONPATH=/workspace .venv/bin/pytest tests/test_endpoint_contract.py tests/test_living_brain.py \
  tests/test_phase_g_mindmap_graph.py tests/test_u2_story_strip.py -q
# plus wave-specific tests
APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/check_learning_loop.sh
curl -fsS "$APP_BASE_URL/api/mindmap/graph" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('nodes')or[]))"
```

After each merge: update board Active row · Ditto `save_memory` STATUS · start next wave.

---

## Definition of DONE

- [ ] W0-A…F merged to `main`
- [ ] Living Focus last-learn shows real HIT/MISS on a graded SN (prod or fixture)
- [ ] Proof band quiet when `ready=false`
- [ ] Unscoped graph readable (&lt;80 nodes) or focus default
- [ ] Mindmap+trail on brain spine
- [ ] No SN1/2/3 stub recs
- [ ] Lock marked DONE; board Active cleared for this track

---

## Human gates (not agent-blocked)

- Merge approval if required
- Close stale PRs #491/#487/#455 after Wave 1 confidence track (separate)
- Telegram ops (out of scope)
