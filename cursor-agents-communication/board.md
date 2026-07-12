# Board — subnet-dashboard concurrent session

**Last updated:** 2026-07-12T14:45:00Z by Cursor Agent A (`-843d`)  
**main:** `19e0ebd`  
**GATE:** J ✅ (#105) · H-thin ✅ (#104) · K ✅ (#107) on `main`

> **Role override (post-K):** Alignment pack is canonical. **Agent A = H-full UI** · **Agent B = Phase L backend**. This supersedes `concurrent-protocol.md` §1 for current parallel work.

---

## Merge queue

| Order | Phase | Agent | Branch | Status |
|-------|-------|-------|--------|--------|
| 1 | **J** Accuracy fix | A | `cursor/phase-j-accuracy-fix-843d` | ✅ merged (**PR #105**) |
| 2 | **H-thin** UI shell | B | `agent-b/phase-h-thin-shell` | ✅ merged (**PR #104**) |
| 3 | **K** CI gates | A + B | `cursor/phase-k-ci-gates` | ✅ merged (**PR #107**) |
| 4 | **H-full** premium UI | **A** | see audit below | 🟡 draft PR — pick branch, merge |
| 5 | **L** signals & alerts | **B** | `cursor/phase-l-signal-pipeline-b061` | 🟡 slice 1 done — PR #115 |

---

## Agent A (`-843d`) — H-full UI

| Field | Value |
|-------|--------|
| Phase | **H-full** premium cockpit (13 sections, Chart.js, `style.css`) |
| Status | UI branches on origin — **not merged to `main`** |
| Recommended branch | `cursor/phase-h-full-premium-ac2c` (20 UI tests, scanner JS, full partial) |
| Alternate | `cursor/phase-h-full-premium-27f3` (Ditto memory `e14eaefa`, 10 UI tests) |
| Backend context only | `cursor/phase-h-full-premium-843d` (builders in `internal/learning/`, no template work) |
| Do not touch | `internal/signals/*`, resolver, grading, learning weights |

---

## Agent B (`-e78a` / `-4e98`) — Phase L

| Field | Value |
|-------|--------|
| Phase | **L** — signals, alerts, WebSocket |
| Branch | `cursor/phase-l-signal-pipeline-b061` |
| PR | #115 (draft) |
| Slice 1 | ✅ `GET /api/signals` + `/summary` + `data/signals.json` |
| Remaining | alerts (`GET/POST /api/alerts`), `/ws/signals`, Jinja context via **server.py only** |
| Do not touch | `templates/*`, `static/*`, resolver, grading weights |

---

## H-full branch audit (2026-07-12)

| Branch | Tip | vs `main` | UI | Chart.js | Tests | Notes |
|--------|-----|-----------|-----|----------|-------|-------|
| `cursor/phase-h-full-premium-ac2c` | `1fe26fc` | +779 / −1407 lines | ✅ `premium_cockpit.html` + scanner JS | ✅ | 20 `test_phase_h_ui` | **Best merge candidate** |
| `cursor/phase-h-full-premium-27f3` | `da37237` | +880 / −1461 lines | ✅ `premium_cockpit.html` + cockpit JS | partial | 10 `test_phase_h_ui` | Ditto-reported complete |
| `cursor/phase-h-full-premium-e78a` | `651694c` | inline `index.html` refactor | ✅ | unclear | expanded | PR #111 era |
| `cursor/phase-h-full-premium-843d` | `7fb8a8d` | backend builders only | ❌ | ❌ | `test_phase_h_full_context` | merge **after** UI branch |
| `cursor/phase-h-full-premium-ui` | `19e0ebd` | equals `main` | ❌ | ❌ | — | empty — ignore |

**On `main` today:** `style.css` linked, 12 cockpit cards, **no Chart.js**, H-full not shipped.

---

## Parallel work (no file overlap)

```text
Agent A: templates/*, static/*, tests/test_phase_h_ui.py
Agent B: internal/signals/*, server.py (router + Jinja context only)
Conflict surface: server.py — coordinate if both open PRs; rebase second merger.
```

---

## Blockers

- None between A and B (parallel OK)
- User merge required before M/N/O

---

## Coordination (Cloud Agents)

```text
Boot:  search_memories("cursor-agents-communication board")
Write: save_memory(content=..., source="cursor-agents-communication")
Do NOT use save_artifact or fetch_memories(["f93f7202"]) for board state.
```

---

## References

- Ditto: `cursor-alignment-prompt-pack.md` (alignment pack — canonical for roles)
- `docs/master-plan-merged.md` §7 (H) · §9 (L)
- `docs/premium-dashboard-redesign.md` (13-section UI spec)
- `cursor-agents-communication/concurrent-protocol.md` (J/H-thin sprint — superseded for H-full/L split)
