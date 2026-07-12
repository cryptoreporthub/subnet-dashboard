# Board — subnet-dashboard concurrent session

**Last updated:** 2026-07-12T05:50:00Z by Cursor Agent A (`-843d`)  
**main:** `19e0ebd`  
**GATE:** H-full in progress — Agent A backend context PR open

---

## Merge queue

| Order | Phase | Agent | Branch | Status |
|-------|-------|-------|--------|--------|
| 1 | **J** Accuracy fix | A | `cursor/phase-j-accuracy-fix-843d` | ✅ merged (#105) |
| 2 | **H-thin** UI shell | B | `agent-b/phase-h-thin-shell` | ✅ merged (#104) |
| 3 | **K** CI gates | A + B | `cursor/phase-k-ci-gates` | ✅ merged (#107) |
| 4 | **H-full** premium UI | A + B | `cursor/phase-h-full-premium-843d` | 🟡 Agent A PR open · Agent B template pending |

---

## Agent A (`-843d`)

| Field | Value |
|-------|--------|
| Phase | **H-full** backend context |
| Branch | `cursor/phase-h-full-premium-843d` |
| Status | 7 context builders wired; pytest green (excl. pre-existing test_simivision import) |

---

## Agent B (`-e78a`)

| Field | Value |
|-------|--------|
| Phase | **H-full** frontend |
| Branch | `cursor/phase-h-full-premium` (shared name; rebase onto A or merge after A) |
| Status | Template + server.py shorten filter per kickoff |

---

## Blockers

- `tests/test_simivision.py` — ImportError `SimiVisionEngine` (pre-existing on main; blocks bare `pytest tests/`)

---

## References

- `docs/premium-dashboard-redesign.md`
- `docs/master-plan-merged.md` §7
- Ditto artifact: phase-h-full-agent-prompts.html (full shapes)
