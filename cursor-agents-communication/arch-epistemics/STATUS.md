# Arch-epistemics STATUS

## Confirmed
- Pin == /version SHA: YES (`c9449d6490231373748f19f299ed19d423a1c971`)
- PR #1294: campaign-only files
- Ditto MCP source tag: **cursor** (not cursor-agents-communication)

## Claims
- SMOKE-001 VERIFIED
- C-014 VERIFIED (code-only partial)
- **F-1: VERIFIED** (code-only partial) — Joshua spotcheck 2026-09-20T00:25Z
  - deltas: PROXY timeout 8→4; WRITE timeout 600→480; MAX_SUBNETS 0→40; TOP_SCORING default 20 / fly NOT_SET
  - live env: NOT_OBSERVABLE (not promoted to Tier A)
  - X-C-016-CAP remains open with F-1 c016_path_routing note
- C-015, C-017: open (Tracer, not dispatched)
- C-016 / X-C-016-CAP: open (feeds F-1; still open after F-1 VERIFIED)

## last_updated
2026-09-20T00:25Z
