# Arch-epistemics STATUS

## Board
Open for verification dispatch only. Rule 8: zero remediation / zero product merges / no issue drafts / no tests / no remediation designs without separate Joshua Go.

## Pin
`c9449d6490231373748f19f299ed19d423a1c971`

## Code-level spine traced (code-only)
Do **not** treat as campaign-complete. Wording is **code-level spine traced, code-only** until Joshua confirms each stamp below.

## Stamp / spot-check provenance
| ID | Status | Spot-check | When (UTC) | Notes |
|----|--------|------------|------------|-------|
| P-CENSUS-002b | VERIFIED (code-only) — Joshua accepted | Tracer produced; Mission Control pin-cite spot-check | 2026-09-20 ~04:35Z produce / Joshua accept same day | desk BOUNDED; score UNBOUNDED |
| P-CENSUS-002c | VERIFIED (code-only) — Joshua accepted | Tracer produced; Mission Control pin-cite spot-check; Ledger confirm | 2026-09-20 ~08:07–08:10Z | T1/T2/T3 late-write / clear-stuck |
| C-018 | STAMPED by Joshua (dual locus + 20/40) | **No separate Tracer raw-blob spot-check of every C-018 cite logged** | 2026-09-20 stamp | Re-verify via C-019 stale-path promotion; do not elevate to VERIFIED without Joshua confirm |

## Active (new — Ditto findings; raw pin cites; ignore Ditto +5)
- **C-019 OPEN → Tracer** — `_heuristic_hunt_pool` / `_focus_tier` / `_UNRANKED` promotion on **stale** path (`internal/subnets/scoring_cap.py` + fresh-path contrast in `score_snapshots.rank_subnets_by_snapshot` `-1.0` fallback)
- **C-020 OPEN → Tracer** — `_compute_technical_indicators` guard + `_degraded_technical_indicators`; trace `degraded` flag + flat `0.5` downstream (composite / snapshot / UI)
- **C-021 OPEN → Tracer** — duplicate `williams_r` key in `_degraded_technical_indicators` literal (`state_vector.py`)

## HOLD
- A2-REPIN
- P-CENSUS-002 causal starvation narrative

## last_updated
2026-09-20T12:16Z
