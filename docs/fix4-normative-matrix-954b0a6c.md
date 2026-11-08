# Fix-4 normative acceptance matrices (auditor mirror)

**Doc-only mirror for auditors (Claude hole 4).** Joshua **GO** 2026-11-08 — normative matrix committed to `docs/`; does **not** authorize Fix-4 implementation.

| Field | Value |
|-------|-------|
| Accepted plan SHA-256 | `954b0a6c2ee0a42783d1b84c8e49398750c8dc84b3ad8a01312157b6815759ad` |
| Excerpt source | `plan-1522-fix4-replit6691536655-contracts-integrated.md` (store; §10–§13 below) |
| PR #1522 head baseline | `c1298fdc870bdb5cc1b7ab8261ec27f532afab62` |
| Tracking issue | [#1573](https://github.com/cryptoreporthub/subnet-dashboard/issues/1573) |
| Implementation PR | [#1522](https://github.com/cryptoreporthub/subnet-dashboard/pull/1522) |

**Still gated:** Ditto + Replit + Claude **PASS** on issue #1573 v4 body; Joshua per-task GO before any Fix-4 task execution.

---

## Inherited product decisions **R-D1..R-D10** (semantics)

Same as integrated plan v2 §11: **compare_blocked → runSuite false**; distinct Compare-blocked titles; dedupe after admission; **Superseded** on verified drift; **BaseUnavailable ≠ PairReadFailed**; refusal key + **runId**; **`writePairResult`** sole `suite:` writer; **`check_gate_state`** read discipline; **`compareReady`** on record; **R-D10** strings **`record-version-mismatch, recompute due`** / **`recomputed`**.

Notation below: **SHA-A** / **SHA-B** = distinct **40-hex** placeholders. Decision **R-D5** = **RD-05a** + **RD-05b**.

---

## 10. Acceptance matrix A — **R-D** closure (**RD-01..RD-10**)

| Row | Fixture | Action | Expected outcome | Prohibited |
|-----|---------|--------|------------------|------------|
| **RD-01** | Mocked `computeGate` → **`next: "compare_blocked"`** | Build `GateNext` / gate actions for delivery | **`gateActions.runSuite === false`** | `runSuite: true` |
| **RD-02** | Mocked **`next: "compare_blocked"`** vs **`next: "await_replit"`** (or other non-blocked waiting) | Check title path for compare-blocked branch | User-facing title **Compare blocked** **not** reused for non-blocked waiting | Same title string for both |
| **RD-03** | `expectedPair` matches; dedupe KV hit; **`workingCheck` open** | Full delivery | Same terminal as no-dedupe fresh post; **no** `kv.put(dedupeKey)` on skip-only path | Dedupe put on skip |
| **RD-04** | `expectedPair` **SHA-A**; live **ReadyPair** **SHA-B** at admission; **`workingCheck` open** | Delivery | **`conclude` `cancelled`**, title **`Superseded`** on **that handle**; admission before dedupe | Non-cancel conclude; second createCheck; dedupe write |
| **RD-05a** | Network returns **BaseUnavailable** (successful compare, absent merge base) | Terminal path dedicated **merge-base unavailable** copy | **≠** PairReadFailed copy | Collapsing to PairReadFailed |
| **RD-05b** | Network returns **`PairReadFailed(compare)`** | Terminal / gate path | **PairReadFailed** handling — **≠** BaseUnavailable terminal | Collapsing to BaseUnavailable |
| **RD-06** | Automated refusal write | Write/read memo | Key **`suite-refusal:{pr}:{head}:{tip}:{mergeBase}`**; value includes **`runId`** | Head-only refusal key |
| **RD-07** | Bypass **`writePairResult` for `suite:`** | Type/test | **Rejected** at compile or test | Alternate writer |
| **RD-08** | Tool: single **`readPr` graph** | `check_gate_state` | **≤1** PR read unless lock forces second | Duplicate full PR fetch |
| **RD-09** | Compare inputs | `advanceGate` persistence | `gateSuiteRecord` includes **`compareReady`** | Omitted |
| **RD-10** | Schema / recompute | record path | **`record-version-mismatch, recompute due`** then **`recomputed`** after repair | Silent carry |

---

## 11. Acceptance matrix B — validated readers (**VR-pgc-01..03**, etc.) — **no proxy “equivalent”**

**Variants:** **V1** = omit `mergeBaseSha`; **V2** = wrong merge base; **V3** = stale `schemaVersion`. **Expected/Forbidden** — same as integrated plan **§8** for each reader × variant (15 rows: 5 readers × 3 variants).

| Row | Variant | Reader | Expected | Prohibited |
|-----|---------|--------|----------|------------|
| **VR-pgc-01** | V1 | `postGateCheck` | not success path; invalid handling per §8 | `unchanged`; dedupe put while invalid |
| **VR-pgc-02** | V2 | `postGateCheck` | same | same |
| **VR-pgc-03** | V3 | `postGateCheck` | same | clean/carry success |
| **VR-psr-01** | V1 | `pairSuiteReady` | **`false`** | **`true`** |
| **VR-psr-02** | V2 | `pairSuiteReady` | **`false`** | **`true`** |
| **VR-psr-03** | V3 | `pairSuiteReady` | **`false`** | **`true`** |
| **VR-rgs-01** | V1 | `readGateState` | **`next === "run_suite"`**; suite not clean/carried | **`next === "mergeable"`** |
| **VR-rgs-02** | V2 | `readGateState` | same | same |
| **VR-rgs-03** | V3 | `readGateState` | same | same |
| **VR-csr-01** | V1 | `compare_suite_runs` carry | **`recorded: false`**, **`reason: "merge-base-mismatch"`**, **`carried: false`**, **`clean: false`** | carry success |
| **VR-csr-02** | V2 | `compare_suite_runs` carry | **`recorded: false`**, **`reason: "merge-base-mismatch"`**, **`carried: false`**, **`clean: false`** | carry success |
| **VR-csr-03** | V3 | `compare_suite_runs` carry | **`recorded: false`**, **`reason: "record-version-mismatch"`**, **`carried: false`**, **`clean: false`** | carry success |
| **VR-tool-01** | V1 | `check_gate_state` | **`baseAvailable`**, **`next`**, **`suite`** as §8 | `mergeable` green; field **`ok`** |
| **VR-tool-02** | V2 | `check_gate_state` | same | same |
| **VR-tool-03** | V3 | `check_gate_state` | same | same |

**`compare_suite_runs` carry `reason` (normative):** **`merge-base-mismatch`** for **VR-csr-01** (omit merge base) and **VR-csr-02** (wrong merge base); **`record-version-mismatch`** for **VR-csr-03** only.

---

## 12. Acceptance matrix C — terminals, dedupe, handle, exception, retry (TC-*)

| Row | Fixture | Action | Expected | Prohibited |
|-----|---------|--------|----------|------------|
| **TC-admit-drift** | Live pair ≠ `expectedPair` at admission; **`workingCheck` open** | delivery | **`conclude` `cancelled`**, title **`Superseded`** on **that** handle; **no** dedupe | Success/failure/action_required conclude |
| **TC-final-drift** | Match at admission; build success intent; **final fence** live ≠ `expectedPair`; handle open | delivery | **`conclude` `cancelled`**, title **`Superseded`** on **existing** handle — **required conclude** | **No** conclude; second handle; non-cancel conclude; dedupe write |
| **TC-dedupe-legacy** | legacy **7-char** dedupe key in KV | delivery | **miss** full fingerprint path | truncated hit |
| **TC-open-update-fail** | `createCheck` ok; `update(in_progress)` throws | delivery | handle retained; **no** second `createCheck` | duplicate create |
| **TC-advance-throw** | `attempt()` throws after open | finalizer | same finalizer as `postGateCheck`; fenced | orphan terminal |
| **TC-reval-retry** | first `conclude` fails; revalidate shows **same** `ReadyPair`; second conclude ok | delivery | **revalidate read** consumes budget before retry; **mut** ≤2 | retry without revalidate |
| **TC-unresolved-confirm** | two mutation attempts fail; **GitHub API** returns confirmable failure | delivery | **`finalization-unresolved`** + log; **no** dedupe | `posted` |
| **TC-pair-unverifiable-confirmed** | exhaustion + cancel mutation **succeeds** | delivery | **`pair-unverifiable`** + check **cancelled** | `finalization-unresolved` |
| **TC-pair-unverifiable-failed** | exhaustion + cancel mutation **fails** within budget | delivery | **`finalization-unresolved`** + log | `pair-unverifiable` posted |
| **TC-cancel-nodedupe** | cancel terminal | delivery | **no** `kv.put(dedupe)` | dedupe on cancel |
| **TC-baseunavail-terminal** | **BaseUnavailable** | delivery | dedicated terminal | PairReadFailed template |
| **TC-reval-drift** | §9 row “Retry revalidation finds drift” | delivery | **Superseded** cancel only | old non-cancel retry |
| **TC-reval-readfail-ok** | §9 “Retry revalidation fails”; cancel mutation **succeeds** | delivery | **`pair-unverifiable`** + check **cancelled**; **no** dedupe | `finalization-unresolved` |
| **TC-reval-readfail-bad** | §9 same fixture; cancel mutation **fails** within budget | delivery | **`finalization-unresolved`** + log; **no** dedupe | **`pair-unverifiable`** success path |
| **TC-double-mut-fail** | §9 last row | delivery | **`finalization-unresolved`** | posted |

---

## 13. Acceptance matrix D — Policy-H1 + fingerprint (**LH-base-move**, **LH-new-automated**, **FP-write**)

| Row | Fixture | Action | Expected | Prohibited |
|-----|---------|--------|----------|------------|
| **LH-base-move** | legacy **needs-joshua** key **K**; base tip moves | gate read | **K** retained; still blocks | auto-clear |
| **LH-new-automated** | new automated refusal | write | pair-scoped key (R-D6) | head-only key |
| **FP-write** | `writePairResult` | KV write | full triple + schema + hold-fp | partial key |
