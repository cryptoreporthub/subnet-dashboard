# Concurrent Execution Protocol — Phase J ∥ H-thin

> **Sprint:** 2026-07-11 concurrent session  
> **Canonical plan:** `docs/master-plan-merged.md`  
> **SciWeave:** `docs/sciweave-answers-phase-j.md`

---

## 1. Agents

| Agent | Suffix | Primary | Secondary |
|-------|--------|---------|-----------|
| **A** | `-843d` | **Phase J** (accuracy fix) | Phase **K** (with B, after H on main) |
| **B** | `-e78a` | **Phase H** (UI) | Phase **L** (after K on main) |

**Phase ownership (later gates):**

| Phase | Owner |
|-------|--------|
| J | A |
| H-thin / H-full | B |
| K | A + B |
| L | B (+ A triggers) |
| M | **A** |
| N | A |
| O | A |

---

## 2. Concurrency and merge order

### Start (parallel)

- **Agent A** may start **Phase J** immediately.
- **Agent B** may start **Phase H-thin** immediately (different files — no routine conflicts).

### H tiers

| Tier | When | Scope |
|------|------|--------|
| **H-thin** | Parallel with J | Link `style.css`, 12 cockpit cards, honest stats, zero `###`, **no Chart.js hero** |
| **H-full** | After **J merged to main** | Chart.js, hero, heat bars, full premium layout |

### Merge (sequential)

1. **Agent A** merges **Phase J** first.
2. **Agent B** rebases **Phase H** on new `main`, merges second.

If both touch shared files, **first merge wins**; second **rebases**.

### Phase gates (do not skip)

| Rule | |
|------|--|
| Agent **A** must **not** start **Phase K** until **Phase H** is on `main` |
| Agent **A** must **not** start **Phase M** until **Phase K** is on `main` |
| Agent **B** must **not** start **Phase L** until **Phase K** is on `main` |

---

## 3. Branch naming

**This sprint:**

```
agent-a/phase-j-<slug>     # e.g. agent-a/phase-j-accuracy-fix
agent-b/phase-h-<slug>     # e.g. agent-b/phase-h-thin-shell
```

Legacy Cloud Agent branches (`cursor/*-843d`, `cursor/*-e78a`) are allowed **outside** this concurrent sprint only.

---

## 4. File ownership

### Agent A OWNS

- `internal/learning/*`, `internal/council/*` (`resolver.py`, `resolver_scheduler.py`, `weights.py`)
- `internal/judges/*`, `internal/cockpit/*`, `internal/mindmap/*`, `internal/store/*`
- `internal/pump/*`, `internal/message_intel/*`
- Phase J modules: `grading.py`, `trace.py`, `deduplication.py`, `regime.py`, `scheduler.py`, `price_reference.py` (new or under paths above)
- `tests/test_phase_j_*.py`, fly/ci for J deps

### Agent A NEVER touches

- `templates/*`, `static/*`
- `internal/analytics/*`, `internal/indicators/*`, `internal/oracle/*`
- `internal/whales/*`, `internal/ruggers/*`, `internal/pump_tracker/*`
- **`mindmap_bridge.py`**, **`trail_bus.py`**, **`trail_events.py`** (extend via new modules only)

### Agent B OWNS

- `templates/*`, `static/*` (`index.html`, `style.css`, `partials/cockpit_cards.html`)
- `internal/analytics/*`, `internal/charts/*` (consumers), `internal/indicators/*`, `internal/oracle/*`
- `internal/whales/*`, `internal/ruggers/*`, `internal/pump_tracker/*`
- `tests/test_phase_h_ui.py`

### SHARED (coordinate via `board.md`)

| File | Rule |
|------|------|
| **`server.py`** | **B** adds guarded `include_router` for H. **A** avoids in J unless board posts `BLOCKED: server.py` |
| **`tests/test_endpoint_contract.py`** | **A** adds J routes in J PR. **B** rebases after J merge; adds `/` + H contracts |
| **`requirements.txt`** | **A** owns J deps. **B** posts on board before UI deps |
| **`fly.toml`** | **A** owns J/scheduler. **B** notifies before changes |
| **`data/*.json`** | **Never commit** local churn. Replay on Fly volume or CI fixtures only |

---

## 5. Cockpit contract (frozen)

**12 section IDs** — do not add API ids without Agent A PR:

`council_picks`, `judges`, `learning_loop`, `predictions`, `scenario_memory`, `pump_ladder`, `pump_tracker`, `trace`, `message_intel`, `mindmap_trail`, `rotation`, `soul_map`

Extra homepage panels in H-full are **layout only**, not new cockpit API sections.

---

## 6. Phase J binding order (Agent A)

1. `docs/sciweave-answers-phase-j.md`
2. `docs/master-plan-merged.md` §6 (J1–J7)
3. Root causes R1–R6

---

## 7. Pre-merge checklist (both agents)

- [ ] `pytest` — **phase tests** (`test_phase_j_*` or `test_phase_h_ui`) + **`tests/test_endpoint_contract.py`**
- [ ] `mypy --strict` on touched Pydantic/modules (best-effort; full tree optional)
- [ ] PR is **not** draft
- [ ] **`board.md`** updated
- [ ] No `data/*.json` churn committed
- [ ] No threshold gaming / fake accuracy
- [ ] Did not edit other agent's owned paths

Known legacy pytest failures: see `AGENTS.md` — do not block J/H on unrelated suites.

---

## 8. Non-negotiables

1. Honest-empty > decorative > 500  
2. Never lower confidence thresholds to fake accuracy  
3. HTML + `style.css` classes in templates — **zero `###`** in rendered `/`  
4. SELL ALERT > HOT when both active  

---

## 9. Board read/write

**Read:** `cursor-agents-communication/board.md` from git (primary for Cursor Cloud).  
**Mirror:** Ditto artifact `10f9ce5f-af7e-45c8-8523-a3c1fd994812` if git lags.  
**Do not** use `fetch_memories(["f93f7202"])` for STATUS this sprint.

**Write:** Update `board.md` when starting work, opening PR, merging, or changing GATE.
