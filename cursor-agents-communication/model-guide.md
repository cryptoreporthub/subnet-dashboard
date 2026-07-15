# Model Guide — Composer vs Grok

**Last updated:** 2026-07-12  
**Applies to:** Agent A (`-843d`), Agent B (`-e78a`), and human-initiated Cloud Agent runs

## Models

| Model | Cursor slug | Best for |
|-------|-------------|----------|
| **Composer** | default Cloud Agent | Scoped implementation, multi-file edits, PR workflow, templates/routes/CI |
| **Grok xhigh** | `grok-4.5-xhigh` | Deep architecture, Phase N pipeline — **use sparingly (high token cost)** |
| **Grok fast-xhigh** | `grok-4.5-fast-xhigh` | **Default for Grok** — audits, sign-offs, design spikes; token-efficient |

**Default:** Composer for both agents unless a trigger in §4 or §5 applies.

**Grok token policy:** Prefer **`grok-4.5-fast-xhigh`** for all subagent sign-offs, audits, and design spikes. Escalate to `grok-4.5-xhigh` only when fast pass returns FAIL/CONDITIONAL with unresolved behavioral risk (Phase N, resolver bugs). Do **not** use full xhigh for routine L/M/O sign-offs.

**Grok as reviewer:** Read-only pass — no edits unless findings require a follow-up Composer task. Save review conclusions to Ditto (`source: cursor-agents-communication`) or a PR comment.

---

## 1. Rule of thumb

| Stay on **Composer** | Switch to **Grok** |
|----------------------|-------------------|
| Spec is written; paths are owned | Ambiguous design or competing branches |
| Templates, REST routes, contract tests | Temporal/logic bugs (grading, replay, live streams) |
| Porting from `server_original` / existing patterns | New subsystem with no repo pattern (WebSocket hub, ingestion, retrain) |
| Board/docs/merge chores | Pre-merge review of >500-line **behavioral** change |
| | Second-opinion audit on merged work (§3) |

**Workflow:** Grok-fast-xhigh audit → Composer implements → Grok-xhigh review before merge (for high-risk slices only).

---

## 2. Phase map — who builds with what

### Completed on `main` (build model used / recommended)

| Phase | Owner | Build with | Grok second opinion? |
|-------|-------|------------|---------------------|
| **A–G** Foundation | Both | Composer | Optional — see §3.1 |
| **I** Root-cause (read-only) | Ditto + agents | Grok-class analysis | ✅ Already reasoning-heavy |
| **J** Accuracy fix | A | Split — see §3.2 | ✅ **Yes — high value** |
| **H-thin** | B (historical) | Composer | Light — see §3.3 |
| **H-full** | A | Composer | ✅ **Yes — medium value** |
| **K** CI gates | Both | Composer | Medium — see §3.4 |

### Active

| Phase | Owner | Build with | Grok second opinion? |
|-------|-------|------------|---------------------|
| **L** Signals & alerts | B (+ A triggers) | Composer slices 1–2; Grok before 3–4 | ✅ Before WebSocket + rules engine |

### Upcoming

| Phase | Owner | Build with | Grok kickoff? |
|-------|-------|------------|---------------|
| **M** Social ingestion | A | Grok design → Composer port | ✅ Yes |
| **N** Calibration / retrain | A | Grok-xhigh design → Composer wire | ✅ **Yes — highest risk** |
| **O** TAO Signal Hub | A | Grok architecture → Composer integrate | ✅ Yes |

---

## 3. Past phases — Grok review checklist (second opinion)

Run these as **read-only Grok-fast-xhigh or Grok-xhigh** passes when touching related code or before M/N/O. Findings → PR comment or Ditto `save_memory`.

### 3.1 Phases A–G (foundation) — optional retrospective

**When:** Before extending cockpit contracts, store queries, or mindmap graph.

| Review target | Grok should verify |
|---------------|-------------------|
| `internal/cockpit/` section IDs | 12 frozen IDs unchanged; honest-empty paths |
| `internal/store/` | Query functions match `/api/store/*` contract |
| `internal/mindmap/` | `{status, nodes[], edges[]}` shape stable |
| `server.py` router mounts | No duplicate route prefixes (historical 422 source) |

**Priority:** Low unless a regression appears.

### 3.2 Phase J — accuracy fix ✅ merged (PR #105)

**When:** Any change to `resolver.py`, `prediction_loop.py`, `portfolios.py`, `weights.py`, or learning stats UI.

| Review target | Grok should verify |
|---------------|-------------------|
| **R1 Horizon integrity** | Late predictions **expire**, not graded against latest price |
| **R1 Replay** | Re-grade uses price at `resolve_at`, not batch snapshot time |
| **R2 Dedupe** | Same netuid + signal within 5 min → one row |
| **R3 Magnitude** | Direction-first grading when `predicted_pct` is proxy |
| **R4 Weights** | Symmetric decay constants; no threshold gaming |
| **R5 Ledger** | Resolver outcomes vs judge portfolios use consistent rules |
| **R6 Trace** | Signal → pick → outcome lineage durable where claimed |
| **SciWeave binding** | Matches `docs/sciweave-answers-phase-j.md` constants |

**Priority:** **High** — wrong-window grading poisons all downstream UI and N/O.

**Build note:** J should have been **Grok for design/root-cause**, **Composer for J1–J7 implementation** once spec locked.

### 3.3 Phase H-thin ✅ merged (PR #104)

**When:** Changing cockpit card partials or honest-empty behavior.

| Review target | Grok should verify |
|---------------|-------------------|
| 12 cockpit sections | Each renders live data or explicit empty state |
| No `###` markdown leaks | Template scan / `test_phase_h_ui` assumptions |
| Stats honesty | Accuracy/P&L not decorated before J replay landed |

**Priority:** Low (superseded by H-full layout).

### 3.4 Phase H-full ✅ merged (PR #120)

**When:** UI regressions, new Chart.js canvases, or PR #110 backend context merge.

| Review target | Grok should verify |
|---------------|-------------------|
| **Honest-empty** | No fabricated chart data; empty states labeled |
| **SELL > HOT** | Alert precedence in UI copy and badge logic |
| **13 sections** | All regions in `premium-dashboard-redesign.md` accounted for |
| **Chart.js binding** | Charts use real API payloads or show empty — not placeholder series |
| **Cockpit contract** | No new API section IDs without `COCKPIT_SECTION_IDS` PR |
| **Markdown sweep** | Zero `###` in rendered HTML |

**Priority:** **Medium** — prevents “polished lies” after J replay.

**Build note:** H-full was correctly **Composer**; Grok is **reviewer/optimizer**, not primary builder.

### 3.5 Phase K ✅ merged (PR #107)

**When:** Promoting gates from report-only to blocking, or CI flakiness.

| Review target | Grok should verify |
|---------------|-------------------|
| Gate 2 contract tests | Cover all `CONTRACT` routes; no false greens |
| Gate 5 Fly validation | Skipped vs required — intentional? |
| Blocking promotion | Which gates should block M/N/O vs warn only |
| `REPO_PAT` / secret names | Exact match in workflow YAML |

**Priority:** Medium before hardening deploy guard.

**Build note:** K was correctly **Composer**; Grok optimizes **policy**, not YAML edits.

---

## 4. Active & future — build + review

### Phase L (Agent B) — 🟢 active

| Slice | Build | Grok review before merge? |
|-------|-------|---------------------------|
| 1 — `GET /api/signals`, persistence | Composer ✅ done | Light — schema honesty |
| 2 — `GET/POST /api/alerts` | Composer | Medium — idempotency, validation |
| 3 — `/ws/signals` WebSocket | **Grok-fast design → Composer build** | **High** — connection lifecycle, fan-out, reconnect |
| 4 — rules engine / correlation | **Grok-fast design → Composer build** | **High** — SELL > HOT, dedup, false-positive rate |
| A triggers (whale/pump/indicator) | Composer | Low — bounded hooks |

**Before B continues:** Grok-fast-xhigh audit **PR #113 vs #115** (read-only) to avoid duplicate work.

### Phase M (Agent A) — future

| Step | Model |
|------|-------|
| Ingestion architecture (Telethon, rate limits, dedup) | Grok-xhigh |
| Port `message_intel/telegram_listener.py` | Composer |
| Prod proof (`message_intel` non-empty) | Composer + manual |

### Phase N (Agent A + B) — approved 2026-07-15

| Step | Owner | Model |
|------|-------|-------|
| N2 scenario-memory outcome wiring | A | Composer 2.5 |
| N3 retrain → cert → fire + scheduler | A | **Grok-xhigh** design → Composer 2.5 wire |
| N1 oracle/grader tuning | B | **Grok-xhigh** design → Composer 2.5 wire |
| N4 backtest harness + analytics | B | Grok-fast design → Composer 2.5 |

### Phase O (Agent A + B) — approved 2026-07-15

| Step | Owner | Model |
|------|-------|-------|
| O1 conviction-threshold alerts (backend) | A | Grok-fast design → Composer 2.5 |
| O4 custom domain + CDN | A | Composer 2.5 |
| O5 docs/handoff | A | Composer 2.5 |
| O2 backtest history UI | B | Composer 2.5 + Grok-fast sign-off |
| O3 exportable per-subnet report | B | Composer 2.5 |

### Agent A optional follow-ups

| Task | Build | Grok review? |
|------|-------|--------------|
| PR #110 backend context builders | Composer | Light — Jinja context shape vs H-full partial |
| L trigger hooks | Composer | Low |

---

## 5. Mid-session switch triggers

Switch the **active** Cloud Agent (or spawn a Grok subagent) when:

1. **“Why?” debugging** — accuracy, P&L, WebSocket, or alert logic still wrong after a Composer fix.
2. **Competing branches** — multiple PRs for same phase (e.g. #113 vs #115, old H-full branches).
3. **New subsystem** — no pattern in repo for WebSocket, ingestion, or retrain.
4. **Pre-merge behavioral review** — >500 lines touching resolver, signals, or grading.
5. **Optimizer pass** — merged phase in §3; user asks “is this still correct?”

**Do not switch** for: CSS polish, `test_endpoint_contract.py` route adds, board/docs, merge/rebase, Ditto STATUS posts.

---

## 6. How to invoke Grok in Cursor

### Cloud Agent model picker
Prefer **`grok-4.5-fast-xhigh`** when manually starting a Grok run (token-efficient). Use `grok-4.5-xhigh` only for high-risk architecture (Phase N, resolver).

### Agent auto-invokes Grok (no manual model switch required)

When `model-guide.md` marks a step **Grok design first** or **Grok review before merge**, the active Composer agent spawns a **read-only Grok subagent** via the Task tool:

| Task | Model | Why |
|------|-------|-----|
| Audits, sign-offs, slice 3–4 review | **`grok-4.5-fast-xhigh`** | Token-efficient; default |
| Phase N retrain, resolver root-cause | `grok-4.5-xhigh` | Only if fast pass insufficient |

User does not need to change the Cloud Agent model picker unless they want the entire run on Grok.

**Workflow:** Grok-fast subagent audit → Composer implements → Grok-fast sign-off before merge.

### Review prompt template (paste into Grok run)
```text
Read-only second opinion. Do not edit files.
Phase:  Paths:  Verify:  Output: PASS / CONDITIONAL / FAIL with file:line findings. ``` --- ## 7. Quick reference — Agent A vs B | Agent | Composer default | Grok for build | Grok for review (past) | |-------|------------------|----------------|------------------------| | **A** | H-full follow-ups, M/O wiring, L triggers | M, N, O kickoff | **J**, H-full, K policy | | **B** | L slices 1–2, server.py routes | L slices 3–4 design | H-thin, L slice 1 schema | --- ## References - `cursor-agents-communication/board.md` — current phase & ownership - `master-plan-merged.md` — phase order - `docs/master-plan-merged.md` — J/R1–R6, contracts, M/N/O detail - `docs/sciweave-answers-phase-j.md` — Phase J grading constants (Grok review binding)