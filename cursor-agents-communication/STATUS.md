# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T14:00:00Z  
**main:** `f264931`

## One-line

**S1 #247 + S2 #250 + B1/S4 #248 on main. Waiting B2/S3 badge → `GATE_S_CORE`. Then A:F1 + B:U1.**

## PR truth

| PR | What | State |
|----|------|-------|
| **#250** | §17.S2 signal-derived magnitude | ✅ **merged** |
| **#248** | §17.S4 honest whale/rugger/indicator depth (B) | ✅ **merged** |
| **#249** | Board GATE_S16 refresh | ✅ **merged** |
| **#247** | §17.S1 conviction bands | ✅ **merged** |
| **#244–#246** | §16.1–16.3 | ✅ **merged** |

## Gates

| Gate | Status |
|------|--------|
| **GATE_S16** | ✅ clear |
| **GATE_S_CORE** | ⏳ need **B2/S3** enrichment badge (S1+S2 done) |

## Next

- **Agent B:** Build **B2** (S3 whale enrichment badge) — unblocks `GATE_S_CORE`
- **Agent A:** Idle until `GATE_S_CORE`, then **A6** F1 watchlist API
- Monitor `./scripts/verify_prod.sh` after deploys
