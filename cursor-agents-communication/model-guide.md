# Model Guide — Composer vs Grok

**Last updated:** 2026-07-15  
**Applies to:** Agent A (`-843d`), Agent B (`-e78a`), and human-initiated Cloud Agent runs

## Models

| Model | Cursor slug / setting | Best for |
|-------|----------------------|----------|
| **Composer** | default Cloud Agent | Scoped implementation, multi-file edits, PR workflow, templates/routes/CI |
| **Grok slow + medium** | Grok 4.5 (slow, not fast) · thinking **medium** | **Default for every Grok call** — design, audits, Step 0, sign-offs |
| **Grok slow + high** | Grok 4.5 (slow) · thinking **high** (`cursor-grok-4.5-high`) | Escalate when medium FAIL/CONDITIONAL or output not satisfactory |

**Default build:** Composer for both agents unless a trigger in §4 or §5 applies.

**Grok thinking policy (mandatory) — user 2026-07-15:**
1. Default = **slow Grok + medium thinking** (not fast, not high, not xhigh).
2. Escalate to **high** only when medium fails or the result is not satisfactory.
3. Do **not** default to `xhigh` or `fast-xhigh`. Use the fast variant only for light chores when able.
4. Prefer a scoped read-only Grok **Task subagent** over switching the whole Cloud Agent run to Grok.

**HARD RULE — Grok lock → Composer write (token-save on output) — user 2026-07-15:**
1. When a slice needs design/thinking, **Grok slow+medium** does the reasoning and returns a **short structured LOCK only** (not a long markdown plan). Cap ~1 screen.
2. **Composer** expands that lock into the plan file / PR body / board lines, then **builds**.
3. Grok must **not** author long prose plans. Composer must **not** invent design details missing from the lock.
4. Lock template (Grok output shape):
   ```
   VERDICT: PASS | CONDITIONAL | FAIL
   DECISIONS: (3–7 bullets)
   FILES: ...
   AC: ...
   RISKS / NON-GOALS: ...
   ESCALATE_HIGH?: no | yes (why)
   ```
5. If an approved auto-plan already names the slice (e.g. `s16-s17-automated-build-plan.md`), **skip a new Grok lock** unless the plan marks DESIGN or the path is ambiguous — Composer builds from the locked plan.

**Grok as reviewer:** Read-only pass — no edits unless findings require a follow-up Composer task. Save review conclusions to Ditto (`source: cursor-agents-communication`) or a PR comment.

**Build caching (token discipline) — try during every slice:**
1. **Read binding docs once per session** — `board.md`, `STATUS.md`, locked spec (`phase-*-step0-spec.md`, `gameplan-*.md`). After that, cite paths; do not re-paste full spec bodies into prompts or Ditto posts.
2. **Stable prefix, variable tail** — when invoking Grok, put unchanged architecture/spec at the top and the slice-specific question at the end so provider prompt-cache can reuse the prefix across calls in the same build.
3. **Scope tools** — `grep`/`read` only owned paths + conflict surface (`server.py`, contract test). No whole-repo exploration when the gameplan already names files.
4. **Batch before Grok** — group related visual/behavioral questions into one slow-medium pass; escalate to high only if that pass fails (see §4 triggers).
5. **Git is the cache of record** — prefer `main` + open PR diff over re-auditing merged reality; update `board.md`/`STATUS.md` once per merge, not every turn.
6. **Skip redundant passes** — if Step 0 / a design note is LOCKED on `main`, Composer builds without a second Grok kickoff unless the slice is novel or medium review failed.

Full token rules: `docs/cursor-implementation-guide.md` § Grok Token-Saving Precautions.

---

## 1. Rule of thumb

| Stay on **Composer** | Switch to **Grok** (slow + **medium** first) |
|----------------------|-------------------|
| Spec is written; paths are owned | Ambiguous design or competing branches |
| Templates, REST routes, contract tests | Temporal/logic bugs (grading, replay, live streams) |
| Porting from `server_original` / existing patterns | New subsystem with no repo pattern (WebSocket hub, ingestion, retrain) |
| Board/docs/merge chores | Pre-merge review of >500-line **behavioral** change |
| | Second-opinion audit on merged work (§3) |

**Workflow:** Grok slow-medium **LOCK** (short) → Composer **writes plan/docs if needed** → Composer **implements** → Grok slow-medium sign-off only if behavioral risk. Escalate to **high** only if medium fails or is unsatisfactory.

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
| **L–M** | A/B | Composer (+ Grok-fast where marked) | See §3 / §4 |
| EXTREME audit / social | Cursor | Composer | Complete |

### Active / approved

| Phase | Owner | Build with | Grok kickoff? |
|-------|-------|------------|---------------|
| **N** Accuracy & Calibration | A (N2/N3) + B (N1/N4) | Composer 2.5; Grok slow-**medium** design first | ✅ Step 0 + per-slice (escalate **high** only if needed) — **COMPLETE** |
| **O** Alerts, Reports, Launch | A (O1/O4/O5) + B (O2/O3) | Composer 2.5; Grok slow-**medium** for O1/N4-related | ✅ Step 0; O2 medium sign-off — **COMPLETE** |
| **P** Prod flags + N1 persist | A | Composer 2.5 | Optional — **COMPLETE** (#232/#237) |
| **§16** Close the trust gap | A (16.1–16.3) | Composer 2.5 | ✅ **COMPLETE** (#244–#246) |
| **§17** Beyond trust gap | A/B by track (S/U/F) | Composer 2.5; Grok slow-**medium** for UI | 🟡 **IN PROGRESS** — S1 #247; `GATE_S16` clear for B |

Full slice tables: §4 below, `gameplan-N-O.md`, `gameplan-phase-16.md`, `gameplan-beyond-16.md`.

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
| Step 0 joint kickoff | A + B | **Grok slow-medium** (escalate **high** only if FAIL/unsatisfactory) |
| N2 scenario-memory outcome wiring | A | Composer 2.5 |
| N3 retrain → cert → fire + scheduler | A | **Grok slow-medium** → Composer 2.5 (escalate high only if needed) |
| N1 oracle/grader tuning | B | **Grok slow-medium** → Composer 2.5 (escalate high only if needed) |
| N4 backtest harness + analytics | B | Grok slow-medium design → Composer 2.5 |

### Phase O (Agent A + B) — approved 2026-07-15

| Step | Owner | Model |
|------|-------|-------|
| O1 conviction-threshold alerts (backend) | A | Grok slow-medium design → Composer 2.5 |
| O4 custom domain + CDN | A | Composer 2.5 |
| O5 docs/handoff | A | Composer 2.5 |
| O2 backtest history UI | B | Composer 2.5 + Grok slow-medium sign-off |
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
2. **Competing branches** — multiple PRs for same phase.
3. **New subsystem** — no pattern in repo for WebSocket, ingestion, or retrain.
4. **Pre-merge behavioral review** — >500 lines touching resolver, signals, or grading.
5. **Optimizer pass** — merged phase in §3; user asks “is this still correct?”

**Always start that Grok pass slow + medium.** Escalate to **high** only if medium fails or is unsatisfactory.

**Do not switch** for: CSS polish, `test_endpoint_contract.py` route adds, board/docs, merge/rebase, Ditto STATUS posts.

---

## 6. How to invoke Grok in Cursor

### Cloud Agent model picker
Default: **Grok 4.5 slow + medium thinking**. Escalate to **high** only after medium FAIL/CONDITIONAL or unsatisfactory output. Do not open xhigh or fast-xhigh by default; fast only for light chores when able.

### Agent auto-invokes Grok (no manual model switch required)

When `model-guide.md` marks a step **Grok design first** or **Grok review before merge**, the active Composer agent spawns a **read-only Grok subagent** via the Task tool:

| Task | Setting | Why |
|------|---------|-----|
| Audits, sign-offs, Step 0, N3/N1 design, O2 review | **slow + medium** | Default |
| Escalate after FAIL / unsatisfactory | **slow + high** | Only if medium insufficient |

**Workflow:** Grok slow-medium subagent → Composer implements → Grok slow-medium sign-off. Escalate high only if needed.

### Review prompt template (paste into Grok run)
```text
Read-only second opinion. Do not edit files.
Phase:
Paths:
Verify:
Output: PASS / CONDITIONAL / FAIL with file:line findings.
```

---

## 7. Quick reference — Agent A vs B

| Agent | Composer default | Grok for build (slow-medium first) | Grok for review (past) |
|-------|------------------|------------------------------------|------------------------|
| **A** | N2, O4, O5, wiring | Step 0, N3, O1 (medium; high rare) | **J**, H-full, K policy |
| **B** | O2, O3, server glue | Step 0, N1, N4 (medium; high rare) | H-thin, L schema |

---

## References
- `cursor-agents-communication/board.md` — current phase & ownership
- `cursor-agents-communication/gameplan-N-O.md` — approved N/O plan + Grok thinking policy
- `master-plan-merged.md` — phase order
- `docs/master-plan-merged.md` — J/R1–R6, contracts, M/N/O detail
- `docs/sciweave-answers-phase-j.md` — Phase J grading constants (Grok review binding)
