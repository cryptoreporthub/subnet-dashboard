# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T17:20:00Z  
**main:** `6d9aad4` (U3 #264)

## One-line

**ONE AGENT + Grok subagent (Pro+). A retired. UI tail: F3 → F4 → F5. Composer 2.5-fast; Grok low/med only.**

## Mode (binding)

| | |
|--|--|
| **Plan** | **Cursor Pro+** — one primary Cloud Agent only |
| **Build** | `composer-2.5-fast` on B scope (`templates/`, `static/`, oracle/analytics UI) |
| **Design** | Grok **slow + low/medium** via **subagent** only — short LOCK |
| **Do not spawn** | Second Cloud Agent (A `-843d` is **retired** for this cycle) |

## PR truth

| PR | What | State |
|----|------|-------|
| **#264** | §17.U3 polish + framing | ✅ **merged** |
| **#263** | §17.F1-F2 watchlist + alert UI | ✅ **merged** |
| **#261** | §17.F6 message-intel (A) | ✅ **merged** |
| **#260** | §17.F5 streaming chat API (A) | ✅ **merged** |
| **#259** | §17.F4 weekly letter API (A) | ✅ **merged** |
| **#257** | §17.F3 paper portfolio API (A) | ✅ **merged** |
| **#258** | §17.U2 story strip | ✅ **merged** |
| **#254–#256** | F1/F2/U1 backends + U1 home | ✅ **merged** |

## Gates

| Gate | Status |
|------|--------|
| **GATE_S16 / S_CORE / HABIT / ACCOUNT** | ✅ all clear |

## Next (one agent queue)

1. **B8** — F3 paper portfolio UI (`s16-s17-automated-build-plan.md`)
2. **B9** — F4 weekly letter UI
3. **B10** — F5 streaming chat UI
4. **Skip unless asked:** U4 light enhance · U5 (needs human F7)
5. **Human:** F7 DNS anytime

**Billing watch:** If usage rows flip to pay-per-use **On-Demand $** beyond included Pro+ pool, **stop and tell the human** (`token-budget-rules.md`).
