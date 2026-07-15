# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T17:58:00Z  
**main:** `6b3c44f` (B10 #270)

## One-line

**ONE AGENT + Grok subagent (Pro+). B10 merged. B11 daily recap in progress.**

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
| **#270** | §17.F5 streaming chat UI (B10) | ✅ **merged** |
| **#268** | §17.F4 weekly letter UI (B9) | ✅ **merged** |
| **#267** | §17.F3 paper portfolio UI (B8) | ✅ **merged** |

## Gates

| Gate | Status |
|------|--------|
| **GATE_S16 / S_CORE / HABIT / ACCOUNT** | ✅ all clear |

## Next (one agent queue)

1. **B11** — **F4b daily recap** — **in progress** (API + home partial)
2. **Skip unless asked:** U4 light enhance · **B12** U5 (needs human F7)
3. **Human:** F7 DNS anytime

**Billing watch:** On-Demand **$** beyond included Pro+ pool → stop and tell human (`token-budget-rules.md`).
