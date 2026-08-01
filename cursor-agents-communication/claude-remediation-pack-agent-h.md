# Claude remediation pack — Agent H Phase 0–2.5 (repo facts)

**Generated:** 2026-08-01 from `origin/main` @ `73a0736`  
**Purpose:** Unblock CONDITIONAL LOCKs — verified file:line facts. Paste this whole file to Claude.

---

## HERO — verified render path (updates your Hero LOCK)

### Single write path (mostly already true)

| Step | What happens |
|------|----------------|
| SSR | `council_stage.html` renders from Jinja `dpick` (= `daily_pick_stage` from server hero context). IDs: `#section-daily-pick`, `#k3-dossier`. |
| Primary hydrate | `cockpit_hydrate.js` fetches `/api/daily-pick` → `renderDailyPick` → `patchK3DossierFromPayload` (patches fields; does **not** wipe dossier HTML). |
| Live refresh | `home_live_refresh.js` `patchHomeDailyCall`: if `#k3-dossier` exists → **delegates** to `window.__cockpitHome.renderDailyPick` (same function). Soft dual-fetch, **not** dual-write wipe race. |
| Stale guard | `shouldApplyDailyPickPayload` compares SSR `data-generated-at` vs payload (`cockpit_hydrate.js` ~1123–1136). |

**AC6 implication:** Do not invent a third writer. Optional cleanup: document “canonical = `__cockpitHome.renderDailyPick`”; ensure live refresh never patches dossier DOM itself.

### SSR conviction / HOLD (council_stage.html)

- Action: `dpick.action` default `'HOLD'` (line ~19)
- Conviction for orb: `final_confidence` / `confidence` / `conviction` on pick|candidate (~50–58). If none → `conviction_pct = 0` (looks empty/broken — matches your live "—" finding)
- Horizon already in SSR: `dpick.time_horizon|default(dpick.horizon|default('24h'))` (~69) — may need **visible badge** if CSS hides it
- Accuracy: only when `trust_banner.ready` (~81–92); else `cal_acc = none` — good for your AC5; verify UI copy shows “building sample size” when not ready / n small
- Warming banner: only if `shell_warming and not sn` (~26–30)

### dashboard_context.py

`build_learning_dashboard_context` (~362–401) supplies Pro/learning panels: `daily_pick`, `mindmap_trail`, `expert_weights`, etc.  
**Above-fold hero prefers** server `daily_pick_stage` / fast hero context — not this alone. Orb must follow the same confidence fields as `/api/daily-pick` + SSR `dpick`.

### Hero files Claude asked for — role summary

| File | Role |
|------|------|
| `council_stage.html` | Above-fold K3 dossier SSR (~1197 lines) |
| `cockpit_hydrate.js` | Sole dossier patcher: `renderDailyPick` ~2432, `patchK3DossierFromPayload` ~1202, export `__cockpitHome` ~3741 |
| `home_live_refresh.js` | Interval refresh; delegates to `__cockpitHome.renderDailyPick` when dossier present (~148–156) |
| `trust_banner_ui.js` | Trust/calibration chrome (~84 lines) |
| `dashboard_context.py` | Learning SSR context for Pro/trail — secondary to hero stage |
| `routes.py` | `/api/daily-pick` + mindmap APIs |

---

## MINDMAP — verified integration matrix

| Source | Writer | Store | API | UI | Closes loop? |
|--------|--------|-------|-----|-----|--------------|
| Council / daily pick | `prediction_loop` + trail append | `predictions.json` + `soul_map.learning_trail` | `/api/daily-pick`, `/api/mindmap/trail` | `renderDailyPick`; Living Focus | **YES** |
| trail_bus events | `trail_bus.emit_*` → `MindmapBridge.append_learning_trail` | `soul_map.json` `learning_trail` | `/api/mindmap/trail`, `/api/mindmap/state` | `renderTrail`; LF teaser | **YES** (evidence bus) |
| Judges | `judges/tracker` → `emit_judge_pnl/postmortem` | portfolios + trail | judges/postmortems APIs; panel summaries | Living Focus judges; mindmap state summaries | **YES** after #720 lands |
| Expert weights | resolver / `nudge_expert` / LearningEngine | soul_map weights | `/api/learning/stats`, `/api/mindmap/summary` | Bench / `renderCouncilWeights` | **YES** |
| Dispositions | selector → emit; soul_map selector output | dispositions + trail | graph `_load_dispositions` | mindmap graph nodes | **Display + trail**; soft-feature scoring is §30 optional (LB-5) — UI must say context vs scoring |
| Scenario | emit + aggregator from scenario_memory | scenario_memory JSON | trail derive; graph scenario nodes | LF chips; graph | **Weak** for scoring — outcomes often not in scorer |
| Pump desk | pump soul_sync emits | pump state + trail | `/api/pump-alerts`; mindmap pump summaries | pump desk UI; graph pump dispositions | **Partial** — parallel UI |
| message_intel | MI soul_sync emits | MI DB + dispositions | `/api/message-intel`; guarded panel summary | proof/MI panels; graph | **Partial** (author trust after #721) |
| Whales / indicators | **No trail_bus writer**; graph loaders only | whale/indicator engines | `/api/mindmap/graph` overlays | `mindmap_graph.js` | **NO** trail loop — read-only overlay |

Aggregator: `collect_trail_events` merges soul_map + predictions + scenario (`mindmap_aggregator.py`).

### Known gaps — updated vs your brief

| Claim | Verified status on main `73a0736` |
|-------|-------------------------------------|
| Stub conviction `50.0` on `/api/mindmap/summary` | **FIXED.** `_mindmap_conviction_block` (`routes.py` ~174–204): uses daily-pick confidence or `data_available: false`, `current: null`. UI must still show honest-empty if clients ignore `data_available`. |
| LB-11 duplicate trail fetch | **PARTIAL.** Hydrate fetches trail; Living Focus prefers cache / listens for `home:hydrate-trail` but can still fetch if cache null. AC: single owner fetch + shared cache. |
| `/api/mindmap/graph` in contract test | **MISSING.** Contract has summary / feedback / story-path only — not graph or trail. |
| Three empty UI blocks on prod | Consistent with empty/warming trail + graph with no nodes + separate Learning Trail SSR — one pipeline (`collect_trail_events`) feeds trail/state/graph; empty store → all empty. Empty state UX is Agent H; wiring more sources into summary = Agent L Phase C. |

### Task 2 vs Agent L (keep)

**You (Agent H):** empty-state UX, node heat/decay, path-trace, edge colors, sparklines aligned to Bench weights, LB-11 dedupe, contract tests for graph+trail, honest “context only” copy for non-scoring signals.  
**Agent L Phase C:** wire display of dev signals / judge portfolios / MI author trend / pump snapshots into summary — **do not plan those here**.

---

## Prior-agent drafts (without full diffs)

Treat as **reference-only ideas**, not salvage audit:
- #692 hero + conviction visual polish + Telegram flagship
- #675 netuid-band accents  
- #633 launch plan hero source-of-truth  
- #374 K3 council hero stack  

Ground-up: your AC list > cherry-picking those PRs.

---

## Suggested gate upgrade

**Hero LOCK:** CONDITIONAL → **PASS** (with AC1–7 as written; note dual-fetch is OK if single patcher).  
**Mindmap LOCK:** CONDITIONAL → **PASS** for audit AC1–7 using matrix above; keep Composer hold on shared mindmap files until Agent L Phase C / human defer; hero Composer can proceed.

If you agree:

```text
READY FOR COMPOSER — hero branch first (cursor/hero-a-tier-ground-up-1d2f).
Mindmap shared-file Composer: BLOCKED until Agent L Phase C merges or human defers.
```

---

## Critical code excerpts

### routes.py — mindmap conviction (no fake 50)

```python
# internal/learning/routes.py ~174-204
def _mindmap_conviction_block(daily_payload):
    """RF-2: no fake 50% — daily pick conviction when present, else honest-empty."""
    # ... reads final_confidence/confidence from daily_payload ...
    # returns data_available True + current pct OR
    # {"data_available": False, "current": None, "explanation": "No aggregated conviction — ..."}
```

### home_live_refresh.js — delegates to cockpit

```javascript
// ~148-156
function patchHomeDailyCall(payload) {
  if (document.getElementById("k3-dossier")) {
    if (window.__cockpitHome && typeof window.__cockpitHome.renderDailyPick === "function") {
      window.__cockpitHome.renderDailyPick(payload);
      return;
    }
  }
  // ... legacy path only if no k3-dossier ...
}
```

### council_stage.html — HOLD + orb %

```jinja
{% set act = (dpick.action|default('HOLD'))|string|upper %}
{# conviction_pct from final_confidence; else 0 — risk: HOLD with 0% looks broken #}
{% set horizon = dpick.time_horizon|default(dpick.horizon|default('24h')) %}
```

### cockpit_hydrate.js — entry points

- `shouldApplyDailyPickPayload` ~1123  
- `patchK3DossierFromPayload` ~1202  
- `renderDailyPick` ~2432  
- `renderTrail` ~2655  
- fetch `/api/daily-pick` ~3452  
- fetch `/api/mindmap/trail?limit=20` ~3610  
- `window.__cockpitHome = { renderDailyPick, ... }` ~3741  
