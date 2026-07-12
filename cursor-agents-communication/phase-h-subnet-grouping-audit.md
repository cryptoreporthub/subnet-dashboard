# Phase H — Per-subnet grouping / collapse (Agent B audit)

**Scope:** Data-flow support for Ave’s optional per-subnet grouping/collapse lane in the premium cockpit.  
**Verdict:** **Frontend-only.** No new backend routes or grouped payloads required.

---

## 1. Implementation note (frontend-only)

### Two independent data planes on `GET /`

| Plane | Context key | Shape | Grouping relevance |
|---|---|---|---|
| **12-card Premium Cockpit** | `cockpit_sections` | `{ status, sections: [{ id, title, summary, metrics, status, updated_at }] }` — **12 fixed panel IDs** | **None.** Panels are thematic (Council, Judges, Pump Ladder, …), not per-subnet. Do not group or collapse these by subnet. |
| **Premium per-subnet context** | `subnets`, `hour_picks`, `day_picks`, `api_indicators_convergence`, `mindmap_trail`, `predictions`, … | Flat lists; per-subnet rows carry `netuid` and/or `id` plus `name` | **Yes.** Grouping is a **view transform** over existing flat lists. |

`server.py` composes both planes on the index route without coupling them:

```247:269:server.py
    context = {
        "request": request,
        "subnets": subnets,
        "data_source": source,
        **learning_ctx,
    }
    ...
        context.update(build_agent_b_root_context(subnets=subnets, data_source=source))
    ...
        context["cockpit_sections"] = load_cockpit_sections()
```

### Canonical join key

Use a single client-side normalizer everywhere grouping happens:

```js
function subnetKey(row) {
  const n = row?.netuid ?? row?.id;
  return n == null ? null : Number(n);
}
```

Display label: `row.name ?? ('SN' + subnetKey(row))`.

**SSR (`subnets` from `_get_subnets_with_source`):** rows are deduped by `netuid` and include `netuid` on live and static-fallback paths.

**Client refresh (`/api/registry`):** rows historically used `id` only. Agent B adds additive `netuid` alias (see §4) so scanner/grouping code does not need registry-specific branching.

**H-full reference:** `premium_cockpit.html` and `premium_scanner.js` already use `netuid ?? id` — follow that pattern.

### How to build grouped UI (Ave)

1. **Roster:** iterate `subnets` (or scanner `state.rows`) as group headers.
2. **Attach panel rows:** for each flat list (`api_indicators_convergence.subnets`, `hour_picks`, `day_picks`, `mindmap_trail`, `predictions`, social cards from `subnets`, etc.), bucket by `subnetKey(row)`.
3. **Collapse state:** pure CSS/JS (`details/summary`, `aria-expanded`, localStorage). No server round-trip.
4. **Optional live merge:** poll existing endpoints (`/api/registry`, `/api/indicators-convergence`, `/api/cockpit/sections`) and re-bucket in JS — still no grouped API.

### What not to do

- Do not add `grouped_by_subnet` to Jinja context unless a future perf study proves client bucketing is too slow (unlikely at ~90 subnets).
- Do not restructure `cockpit_sections` or `internal/cockpit/sections.py` for subnet grouping.
- Do not group by `name` alone — duplicate names across netuids are possible.

---

## 2. Data-shape constraints (document for Ave)

| Variable | Per-subnet? | Join fields | Notes |
|---|---|---|---|
| `subnets` | Roster | `netuid`, `id`, `name`, `status`, `emission`, `apy`, … | Source: `_get_subnets_with_source()` — deduped by `netuid`. |
| `api_indicators_convergence.subnets` | Top 6 by emission | `netuid`, `name` | Not full roster; empty → honest-empty block in template. |
| `hour_picks` / `day_picks` | 1–3 each | `netuid`, `name` | May reference subnets absent from top-N indicator rows. |
| `mindmap_trail` | Events | `subnet` (name string), `netuid` (when derived) | Prefer `netuid` for grouping; name-only rows need name match (fragile if names collide). |
| `predictions` | Rows | `netuid`, `name` | Stable for grouping. |
| `cockpit_sections.sections` | **Not per-subnet** | `id` = panel slug | **Out of scope** for subnet accordion. |
| `/api/registry` | Full registry | `id`, `netuid` (alias), `name`, `status`, … | Scanner + main index `loadData()` use this for 60s refresh. |
| `/api/subnets` | Filtered list | `id`, `netuid` | Live TaoMarketCap when available; `id` defaulted from `netuid`. |

---

## 3. Regression / edge-case checklist

### Empty / sparse data

- [ ] `subnets == []` → single honest-empty state; no zero-height collapse headers.
- [ ] Panel list empty (`api_indicators_convergence.subnets`, `hour_picks`, …) → section-level empty copy unchanged; grouped view shows roster with empty children or hides empty groups (product choice — both valid).
- [ ] `cockpit_sections` cold-deploy fallback still renders **exactly 12** cards (`cockpit_cards.html` canonical list).

### One-item groups

- [ ] Subnet with only one child row (e.g. only in `hour_picks`) still renders; collapse toggle optional (default expanded recommended).

### Duplicate / ambiguous labels

- [ ] Same `name`, different `netuid` → group by `subnetKey`, not name.
- [ ] `mindmap_trail` rows with `subnet` name but missing `netuid` → fallback name match only when `netuid` absent; document as best-effort.
- [ ] `_get_subnets_with_source()` dedupes duplicate `netuid` (last wins) — grouped UI should not assume duplicates in `subnets`.

### ID aliasing

- [ ] Registry `id` === TaoMarketCap `netuid` for the same subnet.
- [ ] Join uses `netuid ?? id` after registry fetch (now both present on `/api/registry`).

### Live refresh

- [ ] Main index `loadData()` (60s): refreshes **registry explorer only** (`#main-stage`, summary grid) — does **not** re-render SSR cockpit cards or premium partials.
- [ ] H-full `premium_scanner.js`: one-shot `/api/registry` on load — grouping state should reset or re-apply after manual re-fetch if Ave adds polling.
- [ ] `/api/cockpit/sections` exists but is **not** wired to auto-refresh in current templates — 12-card grid is SSR-only until page reload.
- [ ] Collapse open/closed state: if Ave persists to `localStorage`, key by `subnetKey` so refresh does not leak state across subnets.

### No regression surfaces

- [ ] `GET /` status 200 and HTML includes `cockpit_cards` + existing partials.
- [ ] `GET /api/cockpit/sections` still returns 12 sections with stable `id` values.
- [ ] `GET /api/registry`, `/api/subnets`, `/api/indicators-convergence` unchanged response contracts (additive `netuid` only).
- [ ] Routes/cards outside premium lane (mindmap graph, judges panel fetch, health, picks APIs) untouched.
- [ ] Agent B root context keys (`pump_analytics`, `api_indicators_convergence`, …) unchanged.

---

## 4. Tiny compatibility fix (applied)

**Problem:** `/api/registry` exposed `id` but not `netuid`, forcing duplicate join logic and risking missed groups when UI only checked `netuid`.

**Change:** `server.py` `get_registry()` — `item.setdefault("netuid", subnet_id)` (additive, backward-compatible).

**Test:** `tests/test_server.py` — assert first registry entry has matching `id` and `netuid`.

---

## 5. Safest implementation path (summary)

1. Ave implements grouping/collapse in **premium partials + JS only** (H-full branch).
2. Use `subnetKey(row) = row.netuid ?? row.id` for all bucketing.
3. Leave **12-card `cockpit_sections` grid flat** — orthogonal feature.
4. No backend churn beyond the `netuid` registry alias unless a future requirement needs server-side pre-grouping (not indicated now).
