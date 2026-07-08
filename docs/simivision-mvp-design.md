---
workflow_id: def73622-373c-45c8-8a98-d19a6403b2ea
subjob_role: mvp-design
source: ditto-code
sourceContext: project subnet-dashboard
date: 2026-06-17
---

# SimiVision Panel — MVP Design Document

## 1. Goal

Make the SimiVision panel on the Subnet Dashboard homepage a **real, always-visible product surface**. The panel must:

- Always render meaningful content, even when the selector has produced few or no decisions.
- Surface **traceable subnet picks** — every card can be traced back to the expert verdicts and brain recommendation that formed it.
- Carry **explanatory metadata** so a user understands *why* a pick is shown and *when* it stops being valid.
- Handle empty and error states gracefully without breaking the rest of the homepage or the `/health` endpoint.

## 2. Current audit findings

- `server.py::_build_simivision_choices()` already derives top-3 cards from selector decisions + brain recommendations + registry metadata.
- The current `data/soul_map.json` only contains **2 decisions**, so the panel currently renders only 2 cards and leaves the 3rd slot blank.
- The template (`templates/index.html`) loops `{% for choice in simivision.choices %}` with **no empty-state branch**; if `choices` is empty the grid is invisible.
- There is no fallback path when selector output is missing, stale, or corrupt.
- Existing failing tests (`tests/test_judge.py`, `tests/test_mindmap_bridge_simivision.py`) show that the self-learning/feedback methods expected by the test suite are not yet implemented. These are **out of MVP scope** for the panel but are noted as follow-up work.

## 3. MVP requirements

### 3.1 Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| SV-MVP-1 | The SimiVision panel always renders at least one meaningful card on the homepage. | Must |
| SV-MVP-2 | Every card displays: subnet id, name, status, recommended action, confidence %, edge score, preferred entry, reward/risk label, horizon, judge agreement, brain target %, and quant/hype/contrarian verdict badges. | Must |
| SV-MVP-3 | If selector decisions are fewer than 3, the panel back-fills from brain recommendations, then from registry highlights, so the "Top 3" promise is kept. | Must |
| SV-MVP-4 | If no signals exist at all, the panel shows a single explanatory empty-state card instead of a blank grid. | Must |
| SV-MVP-5 | Clicking a card opens the existing detail drawer with full traceability metadata (expert breakdown, brain rec, rationale, invalidation). | Must |
| SV-MVP-6 | The `/api/simivision` endpoint returns the same payload shape as the server-rendered template and includes a `meta` object describing fallback provenance and any error. | Must |
| SV-MVP-7 | Errors reading `data/soul_map.json` or `config/registry.json` do not crash the homepage; the panel renders an empty/error state and the rest of the page remains functional. | Must |
| SV-MVP-8 | Existing homepage sections (Spotlight, Network health, Registry table) and `/health` behavior are preserved. | Must |

### 3.2 Non-functional requirements

- **Minimal change**: reuse existing CSS classes, JS drawer logic, and data structures where possible.
- **No new dependencies**: stay within Flask + Jinja + vanilla JS already used by the project.
- **Testable**: add/update tests for `_build_simivision_choices` and the `/api/simivision` endpoint.
- **Traceability**: every surfaced pick must carry `expert_breakdown` and `judge_agreement` so it can be traced back to the verdicts that formed it (preserving prior work).

## 4. Data schema

### 4.1 SimiVision payload

```json
{
  "date": "2026-06-17",
  "choices": [ /* 0–3 Choice objects */ ],
  "alignment_score": 0.75,
  "alignment_status": "aligned",
  "meta": {
    "source": "selector",
    "fallback_used": false,
    "selector_decisions": 2,
    "brain_recommendations": 128,
    "error": null
  }
}
```

### 4.2 Choice object

```json
{
  "subnet_id": 1,
  "name": "Apex",
  "status": "active",
  "action": "accumulate",
  "confidence": 0.85,
  "edge_score": 0.68,
  "preferred_entry": "Stake pool (~24.85% APY)",
  "reward_risk": {
    "ratio": 24.85,
    "label": "High",
    "reward": 24.85,
    "risk_penalty": 0
  },
  "why_now": "Consensus aligns on accumulation; quant emission stability high; hype sentiment bullish; contrarian signal buy.",
  "invalidation": "Consensus score falls below 0.50 or status shifts to at-risk/deprecated.",
  "horizon": "1–3 days",
  "judge_agreement": "Agreed",
  "brain_action": "accumulate",
  "target_weight": 0.8,
  "expert_breakdown": {
    "quant": { "score": 0.85, "metrics": { "emission_stability": "high" } },
    "hype": { "score": 0.9, "sentiment": "bullish" },
    "contrarian": { "score": 0.8, "signal": "buy" }
  },
  "metrics": {
    "emission": 2.975,
    "social_mentions": 1985,
    "apy": 0.2485,
    "total_stake": 496500.0,
    "is_overvalued": false,
    "risk_flags": []
  }
}
```

### 4.3 Fallback provenance (`meta.source`)

| Value | Meaning |
|---|---|
| `selector` | All 3 picks came from selector decisions. |
| `selector+brain` | Selector produced <3 decisions; remaining slots filled from brain recommendations. |
| `brain` | No selector decisions; all picks came from brain recommendations. |
| `registry` | No selector decisions and no brain recommendations; picks derived from registry highlights (top emitters / highest APY). |
| `empty` | No data available; empty-state card rendered. |
| `error` | A data-loading error occurred; `meta.error` contains a short message. |

## 5. Fallback & empty-state design plan

### 5.1 Backend fallback logic

1. **Primary source**: selector decisions sorted by `consensus_score` descending → take up to 3.
2. **Back-fill source 1**: brain recommendations. Exclude subnets already chosen by the selector. Sort by a composite score (`target_weight` × action confidence) and take remaining slots.
3. **Back-fill source 2**: registry highlights. If still <3 picks, use:
   - Top emitter by `emission`
   - Highest APY by `staking_data.apy`
   - Most mentioned by `social_mentions`
   Mark these with `action: "hold"`, `confidence: 0.0`, and `judge_agreement: "No brain signal"`.
4. **Empty state**: if registry is also empty/unreadable, return `choices: []` with `meta.source: "empty"` and `meta.error` set.

### 5.2 Frontend empty-state design

When `choices` is empty, render a single card inside `#simivision-grid`:

- **Icon**: eye-off or signal-off SVG (reuse existing icon style).
- **Headline**: "No live signals today".
- **Body**: "The selector and brain recommendations are currently unavailable. The dashboard will refresh automatically, or you can trigger a refresh."
- **Actions**:
  - "Refresh data" button → calls `POST /api/refresh` (or reloads page if refresh endpoint unavailable).
  - "View health" link → `/health`.
- **Styling**: use existing `.empty-state` class and `.simi-card` container so it visually belongs to the panel.

### 5.3 Error-state design

When `meta.error` is present:

- Render the empty-state card.
- Add a subtle inline error line: "Data source issue: {short error}".
- Do **not** raise an exception or break the Jinja render.

## 6. Error handling strategy

| Scenario | Behavior |
|---|---|
| `data/soul_map.json` missing | Treat as empty selector output; fall back to brain/registry. |
| `data/soul_map.json` invalid JSON | Log exception, treat as empty, set `meta.error`. |
| `config/registry.json` missing | Return empty choices with `meta.source: "empty"` and `meta.error`. |
| `MindmapBridge().get_brain_recommendations()` raises | Catch exception, use empty recommendations dict, set `meta.error`. |
| Fewer than 3 decisions | Back-fill as described in §5.1. |
| `/api/simivision` called directly | Same fallback logic; returns HTTP 200 with `status: "success"` and `meta.error` if applicable. |

## 7. Implementation checklist for downstream tracks

### Backend (`server.py`)
- [ ] Refactor `_build_simivision_choices` to accept a `meta` accumulator and implement fallback tiers.
- [ ] Add helper `_choice_from_registry_item` for registry-highlight picks.
- [ ] Wrap file loads and `MindmapBridge` calls in `try/except`.
- [ ] Ensure `/api/simivision` returns the new `meta` field.
- [ ] Ensure `index()` passes the new payload shape to the template unchanged.

### Frontend (`templates/index.html`)
- [ ] Add `{% if simivision.choices %}` / `{% else %}` branch inside `#simivision-grid`.
- [ ] Build empty-state card markup using existing `.simi-card` and `.empty-state` styles.
- [ ] Wire "Refresh data" button to existing refresh mechanism (or page reload fallback).
- [ ] Update JS `state.simivision` consumption to tolerate `meta.error`.

### Tests
- [ ] Add `test_simivision_fills_from_brain_when_selector_short`.
- [ ] Add `test_simivision_fills_from_registry_when_no_brain`.
- [ ] Add `test_simivision_empty_state_when_no_data`.
- [ ] Add `test_simivision_api_returns_meta`.
- [ ] Verify existing `test_server.py` and `test_freshness.py` still pass.

## 8. Out of MVP scope (noted for follow-up)

- Implementing missing `AdversarialJudge.judge_decision` and `MindmapBridge.log_simivision_*` methods (required by existing failing tests).
- Real-time streaming updates or WebSockets.
- Historical SimiVision performance charts.
- User feedback buttons on each card.

## 9. Success criteria

- Homepage SimiVision panel renders 3 cards when data is healthy.
- Homepage SimiVision panel renders a helpful empty-state card when no data is available.
- `/api/simivision` always returns HTTP 200 with a valid payload.
- Existing tests for server and freshness continue to pass.
- No regression in `/health` or homepage rendering.
