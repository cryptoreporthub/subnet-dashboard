# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T17:45:00Z  
**main:** `58925a7` (B8 #267)

## One-line

**ONE AGENT + Grok subagent (Pro+). B9 in flight. Queue: B9 → B10 → B11 daily recap.**

## Mode (binding)

| | |
|--|--|
| **Plan** | **Cursor Pro+** — one primary Cloud Agent only |
| **Build** | `composer-2.5-fast` on B scope (`templates/`, `static/`; B11 adds thin `internal/letter/`) |
| **Design** | Grok **slow + low/medium** via **subagent** only — short LOCK |
| **Do not spawn** | Second Cloud Agent (A `-843d` is **retired** for this cycle) |

## PR truth

| PR | What | State |
|----|------|-------|
| **#268** | §17.F4 weekly letter UI (B9) | 🟡 **open** |
| **#267** | §17.F3 paper portfolio UI (B8) | ✅ **merged** |
| **#264** | §17.U3 polish + framing | ✅ **merged** |
| **#263** | §17.F1-F2 watchlist + alert UI | ✅ **merged** |

## Gates

| Gate | Status |
|------|--------|
| **GATE_S16 / S_CORE / HABIT / ACCOUNT** | ✅ all clear |

## Next (one agent queue)

1. **B9** — F4 weekly letter UI — **in progress (#268)** — weekly only, **no daily recap in this PR**
2. **B10** — F5 streaming chat UI
3. **B11** — **F4b daily recap** — morning briefing of **yesterday** (API + home partial)
4. **Skip unless asked:** U4 light enhance · **B12** U5 (needs human F7)
5. **Human:** F7 DNS anytime

**Billing watch:** On-Demand **$** beyond included Pro+ pool → stop and tell human (`token-budget-rules.md`).
