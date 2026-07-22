# H1 LOCK — Hour watch live bus (modified option 2 + magic)

**Status:** LOCK APPROVED (plan-only) — **DO NOT EXECUTE until G0 + Wave 1 exit + B0-0; human says `Execute H1`**
**Approved:** 2026-07-22 (human)  
**Revision:** v1.0 — 2026-07-22  
**Slice ID:** H1  
**Viewport:** 390px primary  
**Depends on:** G0 (phone QA after #397) · Wave 1 exit (pump triad + desk trust line) · Batch 0 B0-0 (no Tier‑1 eternal Loading)  
**Canon:** `batch0-brain-presentation-lock.md` v2.1 · `k3-7-k3-vision.md` · `gameplan-pump-site-undeniable.md` S8  
**Supersedes:** s34 rationale “SSE only when `.cockpit-card` exists” for **home** live path (warehouse grid removed Phase H)

---

## 1. What we decided (one page)

### Product

| Decision | Why |
|----------|-----|
| **Hour watch is a first-class surface** | 1h lens is “what council is watching now,” not a secret in Pro drawer |
| **Job = exploratory short lens, not the audited call** | Day/hero owns HOLD/LONG at 45% gate; hour has no HOLD gate today — UI must say so |
| **Implement as K3-7 “Now” chip / rib** | Absorbs horizon chip vision; don’t add a second hero system + chips + Pro grid |
| **Pro drawer = depth, not home** | Gameplan S8: home stays Call + Lead; full hour/day cards stay in `#pro-cockpit` |
| **Magic = orchestrated + change-aware** | Users feel alive when **lead shifts** or surfaces **update together** — not ticker spam |

### Transport

| Decision | Why |
|----------|-----|
| **Modified option 2 — `cockpit.picks` SSE event** | One live bus, one `emitted_at`, atomic hour+day snapshot for rib + drawer |
| **Not option 1 (poll-only)** | Coherence goal; poll can fake magic but duplicates today’s `home_live_refresh` mess |
| **Not option 3a (picks inside `council_picks.metrics`)** | Wrong schema, wrong consumer, rebuilds warehouse for one card |
| **Not unmodified SSE** | Guard blocks on `/`; rebuilds all 12 sections per tick; dual path with 60s poll |
| **Slim tick: picks only on 60s** | `cockpit.sections` slower cadence or on-demand — don’t O(n×12) per tab per minute |
| **§31 O2 compliance** | Kill duplicate refresh — SSE **replaces** hour poll paths, doesn’t add a third |

### Placement (locked)

```text
First viewport (council stage):
  HOLD/LONG call + why + orb          ← S1 / existing hero (no stack redesign)
  Now chip / hour rib (H1)            ← live via cockpit.picks
  24h / 7d chips                      ← static from horizon_views (existing SSR)
  Weighing Room                       ← bench / near-call (S2 owns sort logic)

Below fold:
  Living Focus · Brain letter · Proof band   ← Batch 0

Pro drawer (#pro-cockpit):
  Full hour/day rank cards + KPI + backtest   ← depth; hydrates from same picks event
```

---

## 2. Why not the alternatives (conversation record)

### Why not “fix plumbing / 422s” (VA v1)

APIs are live and articulate (`/api/daily-pick`, `/api/learning/stats`, `/api/ops/readiness`). Failure mode is **presentation**: spinners, “warming up,” hour picks buried and stale. H1 addresses **translation + live orchestration**.

### Why not option 1 alone

Option 1 is valid for a power-user-only surface. We want **engineering coherence and user magic**:

- **Coherence:** one bus, one timestamp, remove SSE-tick + poll overlap (O2).
- **Magic:** `changed` + `previous_lead` push moment; synchronized paint (rib + Pro summary + optional LF nudge).

Option 1 can deliver ~80% of magic with more client glue; option 2 makes **shift moments** and **multi-surface sync** natural.

### Why not unmodified option 2

- `connectCockpitStream()` returns early when no `.cockpit-card` (homepage has zero).
- Each SSE tick calls `get_cockpit_sections()` → 12 builders per connected tab.
- `home_live_refresh.js` already polls every 60s — two mechanisms, one dormant.

### Why simplicity still wins

Magic ≠ complexity users see. Calm authority, honest HOLD, exploratory Now line, one tap to Living Focus. No Bloomberg terminal. `prefers-reduced-motion` on shift whisper.

---

## 3. Conflict check (planned work)

| Plan | Relationship to H1 |
|------|-------------------|
| **G0** phone QA | Run before H1 ship; add Now chip + HOLD+exploratory contrast to checklist |
| **Wave 1 P1–P3** pump | **Before H1** — don’t compete for first viewport with pump lead scanner |
| **Batch 0 B0-0** | **Gate** — no eternal Loading on Tier‑1 before H1 magic |
| **Batch 0 B0-a** LF | H1 tap → LF on hour lead SN (handoff) |
| **Batch 0 LOCK** no hero redesign | H1 = one Now rib/chip only; S1 owns hero internals |
| **K3-7** horizon chips | H1 **is** the Now chip implementation |
| **Gameplan S1** hero 3 ACs | Coordinate — S1 does countdown / vs-hold / evidence; H1 does Now lens only |
| **Gameplan S2** Weighing | Hour = current 1h lead; Weighing = bench — different copy in LOCK |
| **Gameplan S8** Pro demotion | Aligned — rib on home, cards in Pro |
| **§31 O2** kill dual refresh | **H1 must satisfy** — see AC below |
| **K3-8b** pump voice | No hourly % as headline; exploratory lens language |

**Not in H1:** pump triad, hit-rate hero, Weighing sort, brain letter Outlook, 12-card warehouse revival.

---

## 4. Sequencing

```text
G0 complete
  → Wave 1 exit (P1∥P2∥P3 + phone QA)
    → Batch 0 B0-0 green (Tier‑1 no zombie Loading)
      → H1 implement (this LOCK)
        → Wave 3 S1 (hero hardening respects H1 DOM ids)
```

**Parallel OK:** H1 backend (`cockpit.picks` builder) while Wave 1 finishes; **don’t ship** Now rib to prod until G0 + Wave 1 exit.

---

## 5. API contract — `cockpit.picks`

### Event

```text
event: cockpit.picks
id: <emitted_at ISO Z>
data: <json>
```

Emitted on:

1. **Connect** — immediate snapshot (like today’s sections stream).
2. **Every 60s** while connection open (matches `HOURLY_PICK_CACHE_TTL`).
3. **Optional v1.1:** when hour `cache_key` changes mid-interval (true push moment).

`cockpit.sections` may remain on **300s** or REST-only until warehouse grid returns.

### Payload (version 1)

```json
{
  "type": "cockpit.picks",
  "version": 1,
  "emitted_at": "2026-07-22T15:08:12Z",
  "hour": {
    "picks": [
      {
        "rank": 1,
        "netuid": 14,
        "name": "TaoHash",
        "symbol": "TH",
        "score": 72.4,
        "confidence": 0.41,
        "final_confidence": 0.41,
        "action": "long",
        "audited": false,
        "horizon": "1h",
        "generated_at": "2026-07-22T15:07:55Z",
        "reasons": ["Short-horizon state-vector lead"],
        "scenario_tags": {}
      }
    ],
    "meta": {
      "lens": "exploratory",
      "note": "1h watch — not today's audited 24h call",
      "changed": true,
      "previous_lead": { "netuid": 40, "name": "Chunking" },
      "quiet_reason": null
    }
  },
  "day": {
    "action": "HOLD",
    "published": false,
    "reason": "Confidence 29% below 45% audit gate — no long call published",
    "date": "2026-07-22",
    "timestamp_utc": "2026-07-22T08:14:03Z",
    "pick": null,
    "candidate": {
      "netuid": 99,
      "name": "SN99",
      "final_confidence": 0.29,
      "audited": false
    }
  }
}
```

### Server fields (new / derived)

| Field | Source |
|-------|--------|
| `audited` | `final_confidence >= 0.45` (same gate as day engine) |
| `generated_at` | `hourly_pick._PICK_CACHE["ts"]` or `datetime.now(UTC)` on compute |
| `changed` / `previous_lead` | Compare new #1 netuid to module-level last emitted lead |
| `hour.meta.quiet_reason` | When `picks` empty after engine (not fallback emission pick without label) |

Build picks **once** per tick in a shared helper; `summarize_picks()` should read from that snapshot (future dedupe — not required for H1 v1).

---

## 6. UI contract — magic moments

### Now rib / chip (first-class)

**Location:** `#hour-watch-now` inside `council_stage.html` (below call/why, above or beside 24h/7d chips per K3-7).

**Live copy examples:**

- `Now · TaoHash SN14 · 41% · exploratory · updated 1m ago`
- When day HOLD: append `· not today's call` (or equivalent trader English — no “audit gate” drama per K3-7)

**States (Batch 0 VA-08 taxonomy):**

| State | UI |
|-------|-----|
| **Live** | Rib populated + `generated_at` age |
| **Quiet** | `Council quiet on 1h — no name cleared the short lens` |
| **Building** | ≤5s cold only, then Live or Quiet |

### Shift whisper (magic)

When `hour.meta.changed === true` and `previous_lead` present:

- One line under rib, auto-fade 8s: `1h lead shifted · Chunking → TaoHash`
- `prefers-reduced-motion`: no animation; static line only
- No sound, no red flash, no layout jump on tick-without-change (only update “updated Xm ago”)

### Interactions

| Action | Target |
|--------|--------|
| Tap Now rib | `/?focus=<netuid>` → Living Focus (§27) |
| “Open depth” / Pro summary | `#pro-cockpit` opens, scroll `#section-picks` |
| Hash `#section-picks` | `details#pro-cockpit`.open = true |

### Pro drawer (depth)

- `renderHourDayPicks()` from same `cockpit.picks` event — remove deferred-only one-shot as sole source
- Pro `<summary>` line: `Pro · 1h SN14 · HOLD day · updated 1m ago`
- Hour cards keep rank bars; add `Exploratory` chip when `audited: false`
- Label fallback picks: read `scenario_tags.fallback === "highest-emission"`

---

## 7. Implementation plan

### 7a — Backend

| File | Change |
|------|--------|
| `internal/cockpit/picks_snapshot.py` | **NEW** — `build_picks_snapshot() -> dict`; shared hour+day; tracks `previous_lead` |
| `internal/council/hourly_pick.py` | Add `generated_at` to result dict (both branches) |
| `internal/cockpit/routes.py` | Emit `cockpit.picks` on connect + 60s; optional split `_picks_stream` |
| `internal/cockpit/sections.py` | **Defer** — do not call pick engines twice in H1 v1 unless trivial import of snapshot |
| `tests/test_cockpit_picks_stream.py` | **NEW** — `?once=1` emits `cockpit.picks`; schema keys; `audited` bool |

**Stream shape (recommended):** single `/api/cockpit/stream` with **two event types** (`cockpit.picks` every 60s, `cockpit.sections` every 300s or omitted on home).

### 7b — Frontend

| File | Change |
|------|--------|
| `static/js/cockpit_hydrate.js` | Fix guard: connect if `[data-home-live]`; listener `cockpit.picks` → `patchHourWatch()` + `renderHourDayPicks()` + Pro summary; export `patchHourWatch` on `window.__cockpitHome` if needed |
| `static/js/hour_watch_ui.js` | **NEW** — rib render, shift whisper, age formatter, Live/Quiet/Building |
| `static/js/home_live_refresh.js` | **O2:** remove hour/day fetch; on `cockpit.picks` skip redundant daily-pick if `emitted_at` fresh; keep daily-pick/resolved/subnets on interval OR day-only from picks event |
| `templates/partials/premium/council_stage.html` | Add `#hour-watch-now` mount point + SSR fallback from `hour_picks` / horizon_views.now |
| `static/css/council_first.css` | Minimal: rib, shift whisper, exploratory chip |
| `templates/partials/premium/picks.html` | SSR honesty chips; keep structure |
| `static/js/home_deferred.js` | Hash open `#pro-cockpit` when `#section-picks` targeted |

**Visibility / cost controls (H1 v1):**

- `document.visibilityState === 'hidden'` → `EventSource.close()` or pause; reconnect on visible
- Optional: only connect SSE when `#hour-watch-now` in DOM (always true on `/`)

### 7c — Cache bus (O1 alignment)

```javascript
window.HomeHydrateCache = {
  ...
  hourPicks: [],
  dayPick: null,
  picksEmittedAt: null,
  at: Date.now()
};
```

Writer: `cockpit_hydrate.js` on initial hydrate **and** on each `cockpit.picks` event. Readers: `hour_watch_ui.js`, `renderHourDayPicks`, optionally `home_live_refresh` (day sync only).

### 7d — Remove / don’t duplicate

- [ ] `runDeferredPanels` hour/day fetch — fallback only if SSE fails 30s after load
- [ ] `home:cockpit-tick` → full refetch when picks event received in last 5s
- [ ] Rebuild all 12 `cockpit.sections` every 60s per home tab

---

## 8. Acceptance criteria

### Product (390px)

- [ ] Now rib visible **without** opening Pro drawer
- [ ] Hero HOLD + Now exploratory SN **does not feel contradictory** (copy + chips)
- [ ] Tap Now → Living Focus on that netuid
- [ ] Lead shift shows whisper once when `changed: true`
- [ ] Pro drawer shows full cards synced to same `emitted_at` as rib
- [ ] No eternal “Council is convening…” on hour surface after 5s

### Engineering

- [ ] `GET /api/cockpit/stream?once=1` includes `event: cockpit.picks`
- [ ] SSE connects on `/` (`[data-home-live]`)
- [ ] **O2:** single writer for hour refresh — no 60s poll of `/api/top-pick/hour` while SSE connected
- [ ] `generated_at` + `audited` on hour pick API response (REST parity)
- [ ] `tests/test_endpoint_contract.py` unchanged or extended only if new route
- [ ] `pytest tests/test_cockpit_picks_stream.py` green

### Voice (K3-7 / K3-8)

- [ ] No “audit gate” / “blocked” drama on Now rib
- [ ] No hourly % price move as Now headline
- [ ] `exploratory` / `not today's call` when day is HOLD

---

## 9. Tests

| Test | Assert |
|------|--------|
| `test_cockpit_picks_stream_once` | SSE body has `cockpit.picks`; `hour.picks[0].audited` is bool |
| `test_hour_pick_has_generated_at` | REST `/api/top-pick/hour` includes `generated_at` on picks |
| `test_index_has_hour_watch_mount` | `id="hour-watch-now"` in `/` HTML |
| `test_phase_h_no_cockpit_card_grid` | Still zero `.cockpit-card` on home (unchanged) |
| Manual G0 | HOLD hero + Now rib + shift whisper + Pro depth |

---

## 10. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Fly load (N tabs × 60s) | visibility pause; picks-only tick; no 12-section rebuild |
| Batch 0 PR #382 merge conflict | Rebase H1 branch; agree `#hour-watch-now` id before either merges |
| S1 hero work stomps rib | S1 PR must not remove `#hour-watch-now`; coordinate in board |
| Magic feels noisy | shift whisper only on `changed`; no animation on age tick |
| Hour/day engine duplication | shared `build_picks_snapshot()`; refactor `summarize_picks` later |

---

## 11. Explicitly out of scope (H1)

- Daily Call hero stack redesign (K3-7 full reorder — S1)
- Weighing Room sort / mini-compare (S2)
- Pump triad, desk hit-rate %, size cliff (Wave 1)
- Push alerts / wallet chips (Wave 2)
- New `/api/lifecycle` or fourth weight path
- Reviving 12-card warehouse grid on homepage
- Option 3a (picks nested in section metrics)

---

## 12. Definition of done

- [ ] LOCK signed by human
- [ ] G0 + Wave 1 exit + B0-0 gate met
- [ ] H1 AC §8 green on phone 390px
- [ ] O2 satisfied (grep: no parallel hour poll + SSE)
- [ ] board.md updated with H1 queued → done

---

## 13. Human sign-off

```text
H1 LOCK approved — do not execute yet
```

```text
Execute H1 — hour watch live bus
```

---

## Related

- `cursor-agents-communication/batch0-final-merged-plan.md`
- `cursor-agents-communication/k3-7-k3-vision.md` (Now chip)
- `cursor-agents-communication/gameplan-pump-site-undeniable.md` (S8, sequencing)
- `cursor-agents-communication/website-opt-final-plan.md` (O1, O2)
- `internal/cockpit/routes.py` · `static/js/cockpit_hydrate.js` · `static/js/home_live_refresh.js`
