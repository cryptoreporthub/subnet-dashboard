# Model Guide — Composer vs Grok

**Last updated:** 2026-08-16  
**Applies to:** **One primary Cloud Agent** + subagents from the allowlist below. Agent A (`-843d`) **retired** — do not spawn.

> **2026-08-16:** Token-budget **brevity** is retired (`token-budget-rules.md`). Do not force short Grok LOCKs, Composer-fast-only, or terse human replies. `.cursorignore` (skip `data/*.json`) still applies.
>
> **Subagent pool (human 2026-08-16):** Composer **slow** (usual parent/build), Cursor **Grok 4.6 medium**, **GPT-4.6 Luna high**. **Not a hard lane** — each reviews what they are best at; **the other is the final pass**. **Never Sonnet 4.5 or Sonnet 4.6.** Always-on: `.cursor/rules/subagent-models.mdc`.

## Models

| Model | Cursor slug / setting | Best for |
|-------|----------------------|----------|
| **Composer 2.5 (slow)** | `composer-2.5` | **Usual parent / build** |
| **Cursor Grok 4.6 medium** | `inherit` (when parent is Grok 4.6) | Why, design, root-cause — not Grok 4.5 |
| **GPT-4.6 Luna high** | `gpt-5.6-luna-high` | AC / honesty / contract / line-by-line match |

**Forbidden:** Claude Sonnet **4.5** and **4.6** (any effort). Do not use `composer-2.5-fast`, `cursor-grok-4.5-*`, or other families unless the human asks.

**Default build:** **Composer 2.5 slow** (`composer-2.5`).

**Grok thinking policy (mandatory) — user 2026-07-15; updated 2026-08-01:**
1. **Design / audit LOCKs:** start **slow + medium**; escalate to **high** only if medium FAIL / stuck / unsatisfactory. Never default to high / xhigh / fast-xhigh.
2. **Tiny / path-already-clear chores:** **slow + low** is fine.
3. Do **not** open `xhigh` or `fast-xhigh` “just in case.” Fast Grok variant only for light chores when able.
4. Prefer a scoped read-only Grok **Task subagent** over switching the whole Cloud Agent run to Grok.
5. Obey `.cursorignore` — do not pull `data/*.json` or superseded design dumps into context.

**Grok lock → Composer write — retired as a hard token-save (2026-08-16):**
Grok may still return a structured LOCK when that is the useful shape; it is **not** required to stay ~1 screen or to refuse long plans. Composer may write plans and code without waiting on a short LOCK. Historical lock template (optional):
   ```
   VERDICT: PASS | CONDITIONAL | FAIL
   DECISIONS: (3–7 bullets)
   FILES: ...
   AC: ...
   RISKS / NON-GOALS: ...
   ESCALATE_HIGH?: no | yes (why)
   ```

**Review (2026-08-16, not a hard set):** first pass = the model better at *this* question (Grok for why/design/logic; Luna for AC/honesty/contract). **Final pass = the other model.** Do not make Luna the only reviewer or ban Grok from reviewing Composer diffs. Skip the extra passes on one-liners. Neither Grok nor Luna edits in a review seat — findings go back to Composer (or the parent) to patch. Save conclusions to Ditto (`source: cursor-agents-communication`) or a PR comment. Historical “always Sonnet” / “always Luna over Grok” gates are superseded.
**Context hygiene (not brevity):** skip `data/*.json` / `.venv`; prefer `main` + open PR diffs over re-auditing merged work. Billing watch: `token-budget-rules.md`.

---

## 1. Rule of thumb

| Stay on **Composer** | Switch to **Grok** (slow + **medium** first) |
|----------------------|-------------------|
| Spec is written; paths are owned | Ambiguous design or competing branches |
| Templates, REST routes, contract tests | Temporal/logic bugs (grading, replay, live streams) |
| Porting from `server_original` / existing patterns | New subsystem with no repo pattern (WebSocket hub, ingestion, retrain) |
| Board/docs/merge chores | Pre-merge review of >500-line **behavioral** change |
| | Second-opinion audit on merged work (§3) |

**Workflow:** Grok for ambiguous design when useful → Composer implements → Grok sign-off only if behavioral risk. Escalate thinking effort when medium is unsatisfactory. Short LOCK is optional, not required.

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

| Step | Owne

[read_links truncated 3153 chars from this runtime tool output. The full content is stored with the tool result.]