# Plan — Quant attribution + pump desk honesty

**Date:** 2026-07-22  
**Branch base:** `main`

## Slice A — Quant is not the catch-all (Claude LOCK)

**Finding (verified in code):** `_expert_from_signal_source` returns `"quant"` for empty source and for any unmatched label. Learning also does `expert or "quant"`. Snapshot evidence: quant ~1.8× other experts.

**Ship:**
1. Add fifth attribution bucket: `"unclassified"` (not a weighted council expert).
2. Empty / unmatched source → `"unclassified"`, never `"quant"`.
3. Quant only when keywords genuinely match (emission/apy/yield/fundamental/quant).
4. Weight learning **skips** `unclassified` (and unknown) — no silent credit.
5. `/api/learning/stats` surfaces `unclassified_count` (and optionally share).
6. Tests for mapper + learning skip + stats field.

**Merge → Fly → check:** stats show unclassified; quant weight no longer absorbs unknowns.

## Slice B — Pump desk + Council votes UI

**Ship:**
1. Per-card thesis/trigger include name + netuid + flow/score specifics (no identical CHASE RISK boilerplate).
2. Prefer **live ladder / feed name** over stale registry (SN54 = Yanez MIID, not WebGenieAI).
3. Council Votes under conviction: always patch weights when hydrate has them (don’t stick on empty SSR).

**Merge → Fly → check:** pump cards unique; SN54 = Yanez MIID; council votes show Quant/Hype/DH/Technical.

**Correction (2026-07-22):** registry-first was wrong — Yanez is current; WebGenieAI was the stale label.

## Explicit non-goals
- Rebalancing historical soul_map weights in bulk (new attributions only going forward).
- Mixing pump outcomes into council weights.
