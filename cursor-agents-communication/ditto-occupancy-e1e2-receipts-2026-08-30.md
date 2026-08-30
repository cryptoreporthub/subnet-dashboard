# Occupancy E1/E2 — Receipts & Corrections for PR #1137

**Author:** Ditto · **Date:** 2026-08-30
**Purpose:** In-repo record of the #1008 exact-diff resolution + the two corrections (E1/E2) that PR #1137 must fold. Source-of-truth for Cursor; verify against git, not chat.
**Verification chain:** Ditto + Replit read the #1008 diff independently in parallel (2026-08-30) — full convergence, zero contradiction. Both identified the same causal commit.

---

## 1. The #1008 exact-diff item (previously "OPEN") is now CLOSED

PR #1137 currently lists "#1008 exact diff — OPEN". Replace with **"#1008 exact diff — verified"**, and include the full causal commit SHA + the deliberate test change (below).

### The seven commits of #1008 (merged 2026-08-20T22:59:07Z, merge commit d3e331aad)

| SHA | Commit | Role |
|---|---|---|
| 6ad6460e3c | Add tmp boot reaper | scaffolding |
| 8472c37ae8 | Stage 2b soak | scaffolding |
| 5d5c8bbbe3 | Harden v1 freshness gate | unrelated |
| 0769f631c8 | **Prod emergency: scale v1 web VM to shared-cpu-2x (CPU starvation)** | **fly.toml only — see E1** |
| 1eb0a6bfa3 | **Fix daily pick scheduler orphan thread on timeout** | **THE causal code change** |
| b5547c4c07 | Deploy watch note | docs |
| e58ab24555 | Deploy isolation note | docs |

### The four facts (verified at diff/git level)

**(a) Guard removal — 1eb0a6bfa3** (2026-08-20T22:51:57Z, "Fix daily pick scheduler orphan thread on timeout").
Guard ADD side: 8f158de08 (2026-08-13T12:01:26Z, "Prevent overlapping timed-out daily pick work") added _work_thread / _work_thread.is_alive() and the skip message "daily pick tick skipped; previous worker still running". #1008 deletes that check.

**(b) Executor + generation tokens — same commit 1eb0a6bfa3**:
ThreadPoolExecutor(max_workers=1), fut.result(timeout=…), pool.shutdown(wait=False, cancel_futures=True), _work_generation bump on timeout. Test rename is behavioral receipt:
test_daily_tick_skips_when_previous_work_is_still_running → test_daily_tick_timeout_then_immediate_retry_starts_new_worker (timeout → next tick STARTS a new worker; it does NOT wait for the prior one).

**(c) Merged before incident — YES.** Merge commit d3e331aad (2026-08-20T22:59:07Z) is an ancestor of current main 5a33fe6c. Incident began ~2026-08-30T00:15Z — gap ~9d1h16m. **Merge ≠ deploy**: do NOT claim deployment; that requires production release ancestry.

**(d) Side-effect gating (the b3 central claim — code-verified):** the generation-mismatch check runs AFTER get_or_create_today_pick(...) — it gates only the returned payload, NOT in-flight writes. shutdown(wait=False, cancel_futures=True) cannot kill a running future. So an abandoned worker keeps computing AND persisting (HOLD/JSON) while the next tick starts a concurrent call, and #1022's global TMC lock lets the abandoned hold strand the new worker. Chain: #906 guard → removed by #1008 → #1009 forced 15-min retry → #1021 nested non-cancellable workers → #1022 blocking TMC lock.

---

## 2. E1 — ADD #1008's VM-sizing change to the evidence timeline

Commit 0769f631c8 (2026-08-20, "Prod emergency: scale v1 web VM to shared-cpu-2x (CPU starvation)") changed fly.toml shared-cpu-1x → shared-cpu-2x. Current main shows performance-1x / 4GB. Resource-topology history is part of the evidence chain and must appear in the timeline.

---

## 3. E2 — SOFTEN the runtime conclusion to hypothesis level

The fold's "tonight = #906 failure mode re-opened, convoy-multiplied" is fine as FAILURE-MODE framing. Any "resource-level root cause" phrasing is premature. Verbatim replacement:

> The #906 failure mode (#1008 re-opened, #1009/#1021/#1022 amplified) is a code-level causal chain; the exact exhausted resource is UNPROVEN and requires runtime capture (Patch D).

---

## 4. Gate status lines (write verbatim)

- Patch F (static composed-lifecycle): **SATISFIED with receipts** (the #1008 exact-diff item is now closed).
- Patch D (runtime resource capture): **OPEN — gates ranks 2/3/(e), NOT rank 1**.
- Rank 1 (single-flight GET) remains the ONLY mergeable cut; #1138 must NOT merge as-is; 90s stays; KILL=0; #1112/#1113 untouched; #1060 stays open; #1058 stays closed; **no deploy without Joshua**.
- B6 wording: keep **"No deploy without Joshua"** (broader than "no fly-deploy") — retain, don't downgrade.

---

## 5. Scope clamp for #1137

Touch ONLY the plan doc in PR #1137 on cursor/occupancy-scope-plan-d36d. NO code, NO other branches, NO merge, NO deploy, NO comment spam. Push to #1137 only.

---

## 6. Verification instructions (Cursor — do this BEFORE editing)

1. git show each SHA above and confirm each claim against the actual diff: 8f158de08, 1eb0a6bfa3, 0769f631c8, d3e331aad, ancestor-of-5a33fe6c.
2. If ANY receipt is wrong on inspection, **flag it and stop** — do not silently adjust.
3. Output must tick each item (E1 added, E2 reworded, gate lines verbatim) with file + diff-size summary.