# Subnet Dashboard — UX Architecture & Design System

> Role: `ux-architecture`  
> Workflow: `7d56767a-c001-47a0-b803-0d3ef1ff5607`  
> Goal: transform the current Flask/Fly-deployed registry table into a flagship, product-grade dashboard experience.

---

## 1. Product vision

**Product name:** **Subnet Pulse**  
**Tagline:** *Live intelligence for the Bittensor subnet economy.*

The dashboard should feel less like a static table and more like a **mission-control surface** for subnet operators, stakers, and researchers. The narrative arc is:

1. **At-a-glance health** — summary cards answer "How is the network right now?"
2. **Signal discovery** — search, filters, and sorting surface opportunities and risks.
3. **Deep inspection** — expanding a subnet reveals expert consensus, staking economics, and provenance.
4. **Trust & freshness** — every number is tied to a source and a timestamp.

The experience must remain fast on Fly's free-tier (small payload, no heavy JS framework, CSS-first) and deploy-safe (no breaking API changes).

---

## 2. Information architecture

### 2.1 Page structure

```
┌─────────────────────────────────────────────────────────────┐
│  Nav: Logo · Search · Live indicator · Theme toggle          │
├─────────────────────────────────────────────────────────────┤
│  Hero: 4 summary cards (active, at-risk, total emission,     │
│        avg APY) + last-updated timestamp                     │
├─────────────────────────────────────────────────────────────┤
│  Filter bar: Search · Status pills · Risk pills · Sort ·     │
│              View toggle (Table / Cards)                     │
├─────────────────────────────────────────────────────────────┤
│  Main stage:                                                 │
│   • Table view: sortable rows with mini sparklines           │
│   • Card view: grid of subnet cards for mobile               │
├─────────────────────────────────────────────────────────────┤
│  Detail panel (off-canvas / modal):                          │
│   • Header: name, status, risk flags, overvalue badge        │
│   • Consensus meter + recommended action                     │
│   • Staking: total stake, APY, emission rank                 │
│   • Social signal + sources                                  │
├─────────────────────────────────────────────────────────────┤
│  Footer: data attribution, source links, health link         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Primary entities

| Entity | Source | Key fields used in UI |
|--------|--------|----------------------|
| `Subnet` | `/api/registry` | `id`, `name`, `status`, `risk_flags`, `emission_rank`, `staking_data.total_stake`, `staking_data.apy`, `emission`, `social_mentions`, `is_overvalued`, `last_updated` |
| `Consensus` | `/api/soul-map` (proposed) | `subnet_id`, `consensus_score`, `recommended_action`, `expert_breakdown` |
| `Summary` | `/api/summary` (proposed) | aggregated counts, totals, averages |

### 2.3 Status taxonomy

| Status | Color token | Meaning |
|--------|-------------|---------|
| `active` | `--status-active` | Healthy, emitting, no flags |
| `at-risk` | `--status-at-risk` | Emitting but has risk flags (e.g., pruning-risk) |
| `deprecated` | `--status-deprecated` | No longer active / being wound down |
| `unknown` | `--status-unknown` | Missing or stale metadata |

### 2.4 Recommended-action taxonomy

| Action | Color token | Icon idea |
|--------|-------------|-----------|
| `accumulate` | `--action-accumulate` | upward arrow / plus |
| `hold` | `--action-hold` | horizontal dash |
| `reduce` | `--action-reduce` | downward arrow / minus |

---

## 3. Backend / data-shape tweaks

The existing `/api/registry` and `/api/subnet/<id>` routes must remain unchanged. Add the following **new** endpoints so the richer UI can be data-driven without extra client-side computation.

### 3.1 `GET /api/summary`

Returns pre-aggregated hero-card data.

```json
{
  "active_count": 42,
  "at_risk_count": 3,
  "deprecated_count": 1,
  "unknown_count": 82,
  "total_emission": 123.45,
  "avg_apy": 0.1842,
  "total_stake": 12345678.90,
  "total_social_mentions": 98765,
  "overvalued_count": 5,
  "last_updated": "2026-06-10T17:52:17.420373+00:00"
}
```

### 3.2 `GET /api/soul-map`

Exposes `data/soul_map.json` as a lookup keyed by `subnet_id`.

```json
{
  "1": {
    "consensus_score": 0.85,
    "recommended_action": "accumulate",
    "expert_breakdown": { "quant": {...}, "hype": {...}, "contrarian": {...} }
  },
  ...
}
```

### 3.3 Optional: enrich `/api/registry` entries

If the frontend wants to sort/filter by consensus without two requests, add a computed `consensus` object to each registry entry:

```json
{
  "id": 1,
  "name": "Apex",
  ...,
  "consensus": {
    "score": 0.85,
    "recommended_action": "accumulate"
  }
}
```

This is additive only and does not break existing consumers.

---

## 4. Visual design system

### 4.1 Color palette

A dark, high-contrast "neural" theme. All colors are exposed as CSS custom properties in `docs/design-tokens.css`.

| Token | Hex | Usage |
|-------|-----|-------|
| `--bg-base` | `#0B0F19` | Page background |
| `--bg-surface` | `#111827` | Cards, panels |
| `--bg-elevated` | `#1F2937` | Hover states, inputs |
| `--border-subtle` | `#374151` | Dividers, borders |
| `--border-accent` | `#22D3EE33` | Glow borders |
| `--text-primary` | `#F9FAFB` | Headings, primary text |
| `--text-secondary` | `#9CA3AF` | Labels, metadata |
| `--text-muted` | `#6B7280` | Timestamps, placeholders |
| `--accent-cyan` | `#22D3EE` | Primary accent, links, active states |
| `--accent-violet` | `#8B5CF6` | Secondary accent, gradients |
| `--status-active` | `#10B981` | Active status |
| `--status-at-risk` | `#F59E0B` | At-risk status |
| `--status-deprecated` | `#F43F5E` | Deprecated status |
| `--status-unknown` | `#6B7280` | Unknown status |
| `--action-accumulate` | `#10B981` | Accumulate |
| `--action-hold` | `#F59E0B` | Hold |
| `--action-reduce` | `#F43F5E` | Reduce |
| `--overvalued` | `#FB7185` | Overvalued badge |

### 4.2 Typography

- **UI font:** `Inter` (Google Fonts) — weights 400, 500, 600, 700.
- **Data / mono font:** `JetBrains Mono` — for numbers, ranks, IDs, timestamps.
- **Type scale:**
  - Hero metric: `2.5rem / 600 / 1.1`
  - Card label: `0.75rem / 500 / uppercase / letter-spacing 0.05em`
  - Body: `0.875rem / 400 / 1.5`
  - Table header: `0.75rem / 600 / uppercase`

### 4.3 Spacing & elevation

- Base unit: `4px`.
- Page padding: `24px` desktop, `16px` mobile.
- Card radius: `16px`.
- Button / badge radius: `9999px` (pill).
- Input radius: `12px`.
- Shadows:
  - `--shadow-sm`: `0 1px 2px rgba(0,0,0,0.3)`
  - `--shadow-card`: `0 4px 24px rgba(0,0,0,0.35)`
  - `--shadow-glow`: `0 0 24px rgba(34,211,238,0.12)`

### 4.4 Background effects

- Subtle radial gradient "aurora" behind the hero (`--accent-cyan` / `--accent-violet` at 8% opacity).
- Faint dot-grid overlay (`opacity: 0.04`) to reinforce the "network" metaphor.

---

## 5. Layout & responsive behavior

### 5.1 Desktop (≥1024px)

- Fixed top nav, max-width container `1400px`, centered.
- Hero cards in a 4-column grid.
- Filter bar as a single horizontal row.
- Main stage defaults to table view.
- Detail panel slides in from the right (`400px` wide) on row click.

### 5.2 Tablet (768px–1023px)

- Hero cards 2×2 grid.
- Filter bar wraps; search stays full width.
- Table view with horizontal scroll if needed.

### 5.3 Mobile (<768px)

- Hero cards single column, compact.
- Filter drawer triggered by a "Filters" button.
- Default to card view; table view available via toggle.
- Detail panel becomes a bottom sheet or full-screen modal.

---

## 6. Key components

### 6.1 Summary cards

- Glassmorphism surface with a 1px gradient border.
- Large metric in mono font, count-up animation on load.
- Small trend indicator (e.g., "+2 since yesterday") if historical data becomes available.
- Cards:
  1. **Active Subnets** — `active_count`
  2. **At Risk** — `at_risk_count` + risk flags breakdown
  3. **Total Emission** — `total_emission`
  4. **Avg APY** — `avg_apy`

### 6.2 Status badge

- Pill shape with a 6px dot.
- Dot pulses softly for `active` subnets.
- Color derived from status token.

### 6.3 Risk chips

- Small outlined pills, e.g., "pruning-risk".
- Appear in table row and detail panel.

### 6.4 Search & filter UX

- Global search input with `⌘K` / `/` keyboard shortcut.
- Debounced client-side filtering across `id`, `name`, and `status`.
- Status filter pills: All · Active · At-risk · Deprecated · Unknown.
- Risk filter pills: pruning-risk · overvalued.
- Sort dropdown: Rank · APY · Emission · Stake · Social mentions · Consensus score.
- View toggle: Table / Cards.
- Filter state serialized to URL query params for shareability.

### 6.5 Data table

- Columns: ID, Name, Status, Emission, Stake, APY, Rank, Social, Consensus, Action.
- Sortable headers with chevron indicators.
- Row hover lifts slightly and reveals a "Details →" hint.
- Mini horizontal bar (sparkline) in Emission / Stake / Social cells for visual comparison.
- Clicking a row opens the detail panel.

### 6.6 Card view

- Each subnet as a card with:
  - Top row: ID + status badge + action pill.
  - Name as heading.
  - 2×2 grid of key stats (emission, stake, APY, social).
  - Risk chips and overvalued badge if applicable.
  - Tap to open detail panel.

### 6.7 Detail panel

- **Header:** name, status badge, risk chips, overvalued badge, close button.
- **Consensus meter:** radial gauge showing `consensus_score` (0–1) with color bands.
- **Recommended action:** large pill with icon.
- **Expert breakdown:** three small cards for Quant / Hype / Contrarian with scores and top metric.
- **Economics:** emission rank, total stake, APY, emission, social mentions.
- **Provenance:** source link(s) and `last_updated` timestamp.

### 6.8 Live indicator

- Pulsing dot + "Live" label in the nav.
- Auto-refresh every 60s with a subtle toast: "Registry refreshed".

---

## 7. Motion & interaction

- **Entrance:** staggered fade-up for cards and rows (`opacity 0→1`, `translateY 12px→0`, `300ms`, `ease-out`).
- **Hover:** cards/rows lift `translateY(-2px)` and shadow deepens.
- **Focus:** visible focus rings using `--accent-cyan`.
- **Loading:** skeleton screens for summary cards and table; no spinners on full page.
- **Transitions:** panel slide `250ms cubic-bezier(0.4, 0, 0.2, 1)`.
- **Count-up:** summary numbers animate from 0 over `800ms`.
- **Reduced motion:** respect `prefers-reduced-motion` by disabling transforms and count-up.

---

## 8. Accessibility

- Color is never the sole indicator; status badges include text labels.
- All interactive elements have focus states.
- Table uses semantic `<table>` with `<th scope="col">`.
- Detail panel is a dialog with `role="dialog"`, `aria-modal`, and focus trap.
- Sufficient contrast ratios (WCAG AA) for all text on surfaces.

---

## 9. Performance & deploy constraints

- No heavy JS framework; vanilla JS + CSS.
- Single `<style>` block or small `static/dashboard.css`.
- Use `requestAnimationFrame` for count-up and entrance animations.
- Debounce search at `150ms`.
- Cache `/api/summary` and `/api/registry` for 30s if possible (Flask `after_request` headers).
- Keep total first-render payload under `150KB`.

---

## 10. Implementation checklist for downstream subjobs

### Frontend (`templates/index.html` + assets)
- [ ] Import Inter + JetBrains Mono fonts.
- [ ] Implement design tokens from `docs/design-tokens.css`.
- [ ] Build nav, hero summary cards, filter bar, table/card views, detail panel.
- [ ] Wire up `/api/registry`, `/api/summary`, `/api/soul-map`.
- [ ] Implement search, filters, sorting, URL state, view toggle.
- [ ] Add entrance animations, hover states, live indicator, reduced-motion support.
- [ ] Ensure responsive layout.

### Backend (`server.py`)
- [ ] Add `/api/summary` aggregation endpoint.
- [ ] Add `/api/soul-map` endpoint keyed by `subnet_id`.
- [ ] Optionally enrich `/api/registry` entries with `consensus` object.
- [ ] Add short cache headers for registry/summary responses.
- [ ] Verify existing tests still pass.

---

## 11. Open questions

1. Should the dashboard support a light theme? (Recommended: ship dark-only first to control scope.)
2. Do we have historical data for sparkline trends, or should bars represent a single snapshot? (Recommended: snapshot bars for v1.)
3. Should clicking a source link open the raw JSON or a human-readable explorer? (Recommended: open raw source in new tab with an external-link icon.)
