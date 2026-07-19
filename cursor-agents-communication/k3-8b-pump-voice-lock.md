# K3-8b Pump Voice LOCK — Predictive, not lagging

**Status:** LOCKED 2026-07-19 · Grok COPY/PRODUCT (supersedes K3-8 copy patterns)  
**North star:** We are not a crypto page posting hourly % moves. We surface **flow/volume before price chase**.

---

## Product thesis

| Tier | Phases | Trader job | Differentiator |
|------|--------|------------|----------------|
| **LEAD** | STIRRING, ACCUMULATING (lead-gated) | Size early while flow builds | Predictive — buy pressure before price runs |
| **CONFIRMED** | PUMPING | Plan exit / rotation, not fresh entry | Honest chase-risk label |
| **EXIT** | COOLING | Trim before crowd sells | Predictive — flow fading while price may lag |

**Dossier chip (K3-7b)** = early heat on **today's pick only**.  
**This lane** = early heat + confirmed motion **across the universe** (rotation scan).

---

## Lane order & caps

1. LEAD rows first (max 5) — STIRRING + ACCUMULATING, same lead gate as dossier chip (`buy_ratio ≥ 0.55`, `volume_intensity ≥ 0.22`)
2. CONFIRMED rows (max 3) — PUMPING
3. EXIT rows (max 2) — COOLING

Empty when zero LEAD + zero CONFIRMED (EXIT-only does not populate lane).

---

## Copy voice

- Trader English. Action + edge. No audit/ladder jargon.
- **Banned in thesis/trigger:** `ladder`, `composite`, `phase`, `signal_snapshot`, `hysteresis`, `audit gate`, `council scan`, hourly % as headline
- **Allowed:** flow, buy pressure, volume warming, chase risk, trim, rotate, entry window, exit watch

### LEAD — STIRRING

- move: `WATCH · {Name} (SN{n})`
- badge: `EARLY`
- thesis: `Buy pressure building before price runs — {buy}% buy flow, volume still warming.`
- trigger: `Entry window open — small size now or wait for BUILDING confirmation.`

### LEAD — ACCUMULATING

- move: `BUILDING · {Name} (SN{n})`
- badge: `BUILDING`
- thesis: `Flow and volume aligning ahead of price — {buy}% buys, vol {vol}%.`
- trigger: `Best risk/reward band — chase only if you miss this window.`

### CONFIRMED — PUMPING

- move: `CONFIRMED · {Name} (SN{n})`
- badge: `CHASE RISK`
- thesis: `Move is live — you are not early. Use for exit sizing and rotation, not fresh entry.`
- trigger: `Do not chase; trim on EXIT WATCH or rotate to BUILDING names.`

### EXIT — COOLING

- move: `EXIT WATCH · {Name} (SN{n})`
- badge: `FADING`
- thesis: `Buyers stepping away while price may still look hot — {buy}% buy flow left.`
- trigger: `Reduce exposure; lead is shifting to names still BUILDING.`

### Empty

`No lead or confirmed motion right now. Early heat on today's pick stays on the dossier chip when flow warms.`

---

## Section chrome

- Title: **Lead scanner**
- Sub: `Flow before price — early names first, confirmed moves flagged as chase risk.`
- Count pill: `{early_count} lead · {confirmed_count} live`

---

## VERDICT: PASS
