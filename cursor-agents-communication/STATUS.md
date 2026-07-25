# STATUS

**Updated:** 2026-07-25T01:12:00Z  
**main:** `49159d5`+ (#461 docs merged)  
**active plan:** `post-stability-sprint-plan.md`  
**previous plan:** `prod-stability-plan.md` Phases 0–4 ✅ **COMPLETE**

---

## Next (sequential — one PR at a time)

### Wave A — Verify & ops gate
1. ✅ Automated: `./scripts/wave_a_gate.sh` (G0 + pump soak + verify_prod)
2. ⚠️ **Human:** 390px sign-off — Call → Pump desk → horizon path
3. Ops: `fly scale count worker=1` only if prod soak fails after merge

### Wave B — Batch 0 brain (B0-a → B0-d)
3. `cursor/b0-a-living-focus-d2cd` → B0-b → B0-c → B0-d

### Wave C — Pump parity
4. `cursor/p5-founder-chip-d2cd`
5. Rebase #455 social conviction (optional)

### Wave D — Chat
6. `cursor/chat-fast-path-d2cd` — complete Phase 4 AC

### Wave E — Subnet connections (phased)
7. #449 E1 API → E2 UI → E3 macro overlay

### Wave F — Housekeeping
8. Stale doc PRs · E1 test debt · H1 hour-watch (after B0-d)

---

## Done (recent)

- **#461–#464** — prod stability plan (docs + Phases 0–4 implementation)
- **#462** — fast pump-alerts desk, no timeout cache
- **#463** — compact pump desk UI + hydrate desk refresh
- **#464** — sequential hydrate + chat context cache
- **#453–#460** — inline worker, pump desk sparklines, spine polish, conviction orb
- #410 — full plan execution: G0 script, Wave 2–3 (S1–S8), P4 notify

---

## Gameplan slice summary

| ID | Status |
|----|--------|
| Prod stability 0–4 | ✅ |
| G0 | ⚠️ script ✅ · **human 390px open** |
| B0-a…d | ❌ unblocked (B0-0 met) |
| P5 founder chip | ❌ |
| #455 social | ⚠️ open PR, needs rebase |
| #449 integrations | ❌ phased in Wave E |
| H1 hour-watch | — gated on B0-d + G0 |

---

## Skipped / deferred

- Wave 4 pump gameplan depth (YAGNI)
- Full frontend modernization (Batch 0 covers Tier‑1)
- Prediction/weights algorithm rewrite (no evidence of breakage)
