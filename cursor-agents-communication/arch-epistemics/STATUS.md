# Arch-epistemics STATUS

## Pin
`c9449d6490231373748f19f299ed19d423a1c971`

## Joshua VERIFIED (code-only)
C-019, C-020, C-021 (UI + live NOT_OBSERVABLE)

## MC-verified pending Joshua (this turn)
| ID | Verdict |
|----|---------|
| **C-020b** | BOTH_PARTIAL resolved: empty signal_contributions + nested technical_score=0.5; **total does not weight nested technical_score** |
| **C-021b** | **YES** — impact Williams path always unavailable after float overwrite (degraded + non-degraded) |
| **C-015** | Sole atomic writer; success advances mtime; **orphan late-complete refreshes mtime**; no mid-build partial replace |

## Contradiction
**X-C-020-DEGRADED-COMPOSITE → RESOLVED (BOTH_PARTIAL)** via C-020b

## HOLD / human
- A2-REPIN — awaiting Joshua spot-check
- Live probe — DRAFT only, do not run
- SPINE-COMPLETE label held (code-level traced, code-only)

## Rule 8
Locked. No remediation. No product code on PR #1294.

## last_updated
2026-09-20T13:20Z
