# Arch-epistemics STATUS

## Pin
`c9449d6490231373748f19f299ed19d423a1c971`

## VERIFIED (code-only)
- **A2-REPIN VERIFIED** — Joshua spot-check 2026-09-20T15:54Z @ pin (atoms 1–6 cited below)
- P-CENSUS-002b, P-CENSUS-002c
- C-019, C-020, C-021 (UI + live NOT_OBSERVABLE)
- **C-020b, C-021b, C-015** — MC PASS; ready for Joshua accept (answers below)

## A2-REPIN atoms (Joshua)
1. Unbounded loop — `score_snapshots.py:189–218`
2. Caller timeout/abandon — `:381–390`
3. Single-flight — `:318–326` & `:395–397`
4. Cosmetic stuck-clear — `:471–493`
5. Desk bounded ≤60s — `desk_snapshot.py:20–22` & `:55–62`
6. Context-manager stall — `server.py:782–784`; `chat_service.py:135–137`; `dashboard_context.py:120–122`; `worker_proxy.py:752–753`

## Timeout spine
Code-level traced, code-only — caller timeout → orphan late write. COMPLETE label optional; causal map accepted via A2-REPIN.

## C-020b / C-021b / C-015 answers (already Tracer+MC)
See results/*.json. Headlines in Mission Control report this turn.

## Contradiction
X-C-020-DEGRADED-COMPOSITE → RESOLVED BOTH_PARTIAL

## Live probe
DRAFT ONLY — do not run

## Rule 8
Locked. Zero remediation. Zero product code on PR #1294.

## last_updated
2026-09-20T15:54Z
