# Fix-4 normative acceptance matrices (auditor mirror)

**Doc-only mirror for auditors (Claude hole 4).** Joshua **GO** 2026-11-08 — normative matrix committed to `docs/`; does **not** authorize Fix-4 implementation.

| Field | Value |
|-------|-------|
| Accepted plan SHA-256 | `954b0a6c2ee0a42783d1b84c8e49398750c8dc84b3ad8a01312157b6815759ad` |
| Excerpt source | Integrated plan §8–§13 (self-contained below; authority SHA above) |
| PR #1522 head baseline | `c1298fdc870bdb5cc1b7ab8261ec27f532afab62` |
| Tracking issue | [#1573](https://github.com/cryptoreporthub/subnet-dashboard/issues/1573) |
| Implementation PR | [#1522](https://github.com/cryptoreporthub/subnet-dashboard/pull/1522) |

**Still gated:** Ditto + Replit + Claude **PASS** on issue #1573 **v5** body; Joshua per-task GO before any Fix-4 task execution.

**Doc-only PR [#1574](https://github.com/cryptoreporthub/subnet-dashboard/pull/1574):** no `fly-deploy` / no production deploy. Committed file byte `sha256` vs accepted plan `954b0a6c…` stated on PR comment when updated.

**Full-suite admissibility (Tasks 1 & 3c):** `pytest-junit` for exact head **and** workflow **Run full suite** step **success**. Cancelled suite step with artifact (e.g. `c1298fdc` run `42430270854`) is **not** a tranche baseline.

---

## Inherited product decisions **R-D1..R-D10** (semantics)

Same as integrated plan v2 §11: **compare_blocked → runSuite false**; distinct Compare-blocked titles; dedupe after admission; **Superseded** on verified drift; **BaseUnavailable ≠ PairReadFailed**; refusal key + **runId**; **`writePairResult`** sole `suite:` writer; **`check_gate_state`** read discipline; **`compareReady`** on record; **R-D10** strings **`record-version-mismatch, recompute due`** / **`recomputed`**.

Notation below: **SHA-A** / **SHA-B** = distinct **40-hex** placeholders. Decision **R-D5** = **RD-05a** + **RD-05b**.

---

## 8. Trust-reader outputs by variant (V1 / V2 / V3)

**Shared setup:** Live **`ReadyPair`** with valid 40-hex triple; KV suite record **clean-equivalent** with invalid pair metadata; gate verdicts + Replit tag **seeded passing**.

| Variant | Invalid record cause | Notes |
|---------|----------------------|-------|
| **V1** | `mergeBaseSha` omitted from stored record | Same assert/forbidden **pattern** as V0 row below; `compare_suite_runs` carry **`reason: "merge-base-mismatch"`** |
| **V2** | `merge-base-mismatch` — stored **`mergeBaseSha` ≠ live** | Identical reader pattern as V0 |
| **V3** | `record-version-mismatch` — stored **`schemaVersion` ≠ READER_EXPECTED** | Identical reader pattern as V0; carry **`reason: "record-version-mismatch"`** only for V3 |

**V0 reference pattern** (apply per variant with the invalid cause above):

| Reader | Exact assert | Forbidden |
|--------|--------------|-----------|
| **`postGateCheck`** (dedupe hit + open **`workingCheck`**) | `conclude` **`action_required`**; output.title **`Gate waiting`**; output.summary **includes** **`record-version-mismatch, recompute due`** (R-D10); **`CheckPost` === `posted`** | **`success`**, **`unchanged`**, dedupe **`kv.put`** while record invalid |
| **`pairSuiteReady`** | return **`false`**; **`tag-replit`** + **`ask-replit`** → **`skipped:stale-pair`**; **no** tag/ask side effects; test header states **`alignedPair` supplied or absent** per fixture (§11 V1–V3 delivery: **absent**, `observePair`; `advance.ts:131–157`) | **`true`**; tag/ask posted |
| **`readGateState`** | **`next === "run_suite"`**; **`suiteDetail` === `record-version-mismatch, recompute due`** (per V1–V3); suite not `clean`/`carried` (**no** `baseAvailable` on return — fixture uses **`mergeBaseSha`**, not `baseSha`) | **`next === "mergeable"`**; detail omitted; assert `baseAvailable` only via **`check_gate_state`** row |
| **`compare_suite_runs`** carry | **`recorded: false`**, **`carried: false`**, **`clean: false`**; **`reason`** per variant row above | **`recorded: true`**, **`carried: true`**, **`clean: true`** |
| **`check_gate_state` tool** | Fields present: **`headSha`**, **`next`**, **`suite`**, **`baseAvailable`**; **`baseAvailable === true`** when observation is **`ReadyPair`**; **`next === "run_suite"`**; **`suite`** not `clean`/`carried` | `next === "mergeable"` as green; invented **`ok`** field |

---

## 9. Deterministic finalizer cases

**Split rule:** Where design requires GitHub confirmation vs log/unresolved, use **two** bounded fixtures (mutation confirm vs fail) — **one** typed outcome each (**no** `or` in the assertion).

| Fixture (sequence) | Expected check/result/KV/log | Forbidden effects |
|--------------------|------------------------------|---------------------|
| Admission recovery: `expectedPair` ReadyPair A; admission read 1 `PairReadFailed(compare)`, read 2 ReadyPair A; non-green gate; final fence A; `workingCheck` open | Same-handle **`action_required`** conclude; return **posted**; one dedupe put **after** confirmed conclude | BaseUnavailable, new handle, reads beyond admission 2 + final fence 2, pre-conclude dedupe put |
| Admission exhaustion: both admission reads `PairReadFailed`; `workingCheck` open | Same-handle **cancelled**, title **Pair unverifiable**; **`pair-unverifiable`** only if GitHub confirms; no dedupe | Superseded claim, non-cancel conclude, dedupe before admission, new handle |
| Admission exhaustion, no handle | **`pair-unverifiable`**; no check mutation; no dedupe | `createCheck` or `conclude` |
| Final-fence recovery: admission A; success intent from valid clean record; fence read 1 fails, read 2 ReadyPair A; handle exists | Same-handle **success** conclude; **posted**; one dedupe after confirmed conclude | PairReadFailed as BaseUnavailable, success before second read, extra handle |
| Final-fence exhaustion: admission A; both fence reads fail; handle exists | Same-handle **cancelled**, title **Pair unverifiable**; **`pair-unverifiable`** only if GitHub confirms; no dedupe | success/failure/action_required conclude, Superseded without mismatch evidence, new handle |
| Final-fence exhaustion, no handle | **`pair-unverifiable`**; no mutation; no KV write | createCheck to cancel, conclude, dedupe write |
| Retry revalidation finds drift: conclude fails; revalidation returns ReadyPair B ≠ A | Remaining mutation: same-handle **cancelled** **Superseded**; **`stale-head`** only if cancel confirmed; no dedupe | Retry old non-cancel conclusion, new handle, **posted** |
| Retry revalidation fails: conclude fails; both revalidation reads `PairReadFailed` | Same-handle cancel **Pair unverifiable** within budget; **`pair-unverifiable`** if confirmed else **`finalization-unresolved`** + log; no dedupe | Retry without matching pair, BaseUnavailable, new handle, false **posted** |
| Required terminal mutation fails twice; handle unconfirmed | **`finalization-unresolved`** + `gate_check_github_failure` (phase, counters) | Dedupe write, new handle, **posted** |

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

**RD-03 vs §9 dedupe:** **RD-03** is the **skip-only / dedupe-hit** path (reuse terminal, no redundant dedupe write). **§9** recovery rows (e.g. admission recovery) assume a **confirmed non-cancel conclude** and **posted** terminal — plan allows **one** `kv.put(dedupeKey)` **only after** that confirmed conclude, not on skip-only (see accepted plan §5–§6).

---

## 11. Acceptance matrix B — validated readers (**VR-pgc-01..03**, etc.) — **no proxy “equivalent”**

**Variants:** **V1** = omit `mergeBaseSha`; **V2** = wrong merge base; **V3** = stale `schemaVersion`. **Expected/Forbidden** — **§8** tables above (15 rows: 5 readers × 3 variants).

| Row | Variant | Reader | Expected | Prohibited |
|-----|---------|--------|----------|------------|
| **VR-pgc-01** | V1 | `postGateCheck` | **`action_required`**; title **Gate waiting**; summary has **record-version-mismatch, recompute due**; **posted** | **success**; **unchanged**; dedupe put while invalid |
| **VR-pgc-02** | V2 | `postGateCheck` | same pattern as §8 V0 row | same |
| **VR-pgc-03** | V3 | `postGateCheck` | same pattern as §8 V0 row | clean/carry success |
| **VR-psr-01** | V1 | `pairSuiteReady` (**delivery**) | **`false`** (trusted-record branch); **`skipped:stale-pair`** tag+ask; no side effects; **`alignedPair` absent** in header | **`true`**; tag/ask |
| **VR-psr-02** | V2 | `pairSuiteReady` (**delivery**) | same pattern; wrong `mergeBaseSha` variant | same |
| **VR-psr-03** | V3 | `pairSuiteReady` (**delivery**) | same pattern; stale `schemaVersion` variant | same |
| **VR-rgs-01** | V1 | `readGateState` (**gate-state**) | **`run_suite`**; **`suiteDetail`=`record-version-mismatch, recompute due`**; record absent (**no** `baseAvailable` assert) | **`mergeable`**; wrong detail; `baseAvailable` on tool row only |
| **VR-rgs-02** | V2 | `readGateState` (**gate-state**) | same **`suiteDetail`**; wrong `mergeBaseSha` | same |
| **VR-rgs-03** | V3 | `readGateState` (**gate-state**) | same **`suiteDetail`**; stale `schemaVersion` | same |
| **VR-csr-01** | V1 | `compare_suite_runs` carry | **`recorded: false`**, **`reason: "merge-base-mismatch"`**, **`carried: false`**, **`clean: false`** | carry success |
| **VR-csr-02** | V2 | `compare_suite_runs` carry | **`recorded: false`**, **`reason: "merge-base-mismatch"`**, **`carried: false`**, **`clean: false`** | carry success |
| **VR-csr-03** | V3 | `compare_suite_runs` carry | **`recorded: false`**, **`reason: "record-version-mismatch"`**, **`carried: false`**, **`clean: false`** | carry success |
| **VR-tool-01** | V1 | `check_gate_state` | **`headSha`**, **`next`**, **`suite`**, **`baseAvailable`** present; **`baseAvailable === true`** (ReadyPair); **`next === "run_suite"`**; suite not clean/carried | **`next === "mergeable"`**; field **`ok`** |
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
