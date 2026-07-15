# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T06:20:00Z  
**main:** `ab1936c`

## One-line

**Phase P code merged via #232 (not #233). Prod flags on; P5 verified (#237).**

## PR truth (avoid board drift)

| PR | What | State |
|----|------|-------|
| **#232** | Phase P implementation — `fly.toml` flags, `subnet_snapshot`, judge persist | ✅ **merged** |
| **#233** | Agent B duplicate of #232 | ❌ **closed unmerged** — do not wait on this |
| **#237** | P5 prod verify + `scripts/verify_prod.sh` | ✅ **merged** |

## Done (do not re-queue)

| Track | PRs |
|-------|-----|
| N/O | **#227** · **#228** |
| Phase P code | **#232** |
| Phase P verify | **#237** |
| Board hygiene | **#229**–**#234** · **#236** |

## Phase P — COMPLETE (verified on prod)

- `./scripts/verify_prod.sh` → auto_retrain **on**, conviction alerts **on**
- Backtest: council/oracle **53.5%**; oracle ≥0.55 bin **69.8%** (n=116)
- **P4 pending:** custom domain DNS — human (`DEPLOY.md`)

## Next

- **READY FOR REVIEW:** `s16-s17-automated-build-plan.md` + `s16-s17-start-prompts.md` — approve then Build A1.
- Agent A (`-843d`): §16 → S1/S2 → F1–F6. Agent B (`-e78a`): idle until `GATE_S16`, then S4→S3→U*→F UIs.
- Monitor `./scripts/verify_prod.sh` after deploys
