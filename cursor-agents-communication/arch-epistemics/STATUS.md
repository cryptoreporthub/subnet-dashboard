# Arch-epistemics STATUS

## Pin
`c9449d6490231373748f19f299ed19d423a1c971`

## Joshua accepted (VERIFIED code-only)
- C-019, C-020, C-021 — scope: UI NOT_OBSERVABLE; live env NOT_OBSERVABLE
- P-CENSUS-002b, P-CENSUS-002c VERIFIED code-only
- C-018 STAMPED (full Tracer cite spot-check still pending for COMPLETE label)

## Open contradiction
- **X-C-020-DEGRADED-COMPOSITE** — Ditto empty signal_contributions vs Tracer flat 0.5 in expert_contributions  
  MC note (BOTH_PARTIAL): degraded return sets `signal_contributions={}` AND `technical_score=0.5` (`state_vector.py:632-641`); both embedded under `expert_contributions` (`:1759-1763` / `:1913-1917`). Follow-up **C-020b**: how composite/total treats the 0.5.

## Active → Tracer
- **C-020b** — composite treatment of degraded 0.5
- **C-021b** — impact path always unavailable after float overwrite?
- **C-015** — what updates `data/score_snapshots.json` mtime; can partial/orphan write refresh it?

## HOLD / next human
- **A2-REPIN** — awaiting Joshua spot-check
- Live probe — **DRAFT ONLY** (`probes/PROBE-LIVE-CONFIG-DRAFT.md`); approver Joshua; do not run
- SPINE-COMPLETE label held (code-level traced, code-only)

## Rule 8
Locked. No remediation. No product code on PR #1294.

## last_updated
2026-09-20T13:17Z
